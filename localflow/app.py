"""LocalFlow app: config + tiering + tray + hotkey → recorder → transcriber → inject."""

import logging
import threading
import time
from collections import deque

from localflow import config, sounds, vocab
from localflow.audio import Recorder
from localflow.hotkey import PushToTalk
from localflow.inject import inject_text
from localflow.tiering import has_nvidia_gpu, pick_tier
from localflow.transcribe import Transcriber, model_for_language

log = logging.getLogger(__name__)

MIN_AUDIO_SECONDS = 0.8  # ignore takes with essentially no speech (incl. pre-roll)
TAP_SECONDS = 0.4        # combo released faster than this = tap (auto-stop mode)


class LocalFlowApp:
    def __init__(self) -> None:
        self.settings = config.load()

        if self.settings.model == "auto":
            if self.settings.tiered_model:  # benchmark already ran on this machine
                model, device = self.settings.tiered_model, "cpu"
                if has_nvidia_gpu():
                    device = "cuda"
            else:
                model, device = pick_tier()
        else:
            model, device = self.settings.model, "cpu"
        # '.en' models only for explicit English; multilingual otherwise.
        model = model_for_language(model, self.settings.language)
        hint = self.settings.language_hint
        try:
            self.transcriber = Transcriber(model_name=model, device=device,
                                           language_hint=hint)
        except Exception:
            if device != "cpu":
                log.exception("%s on %s failed, falling back to CPU", model, device)
                device = "cpu"
                self.transcriber = Transcriber(model_name=model, device="cpu",
                                               language_hint=hint)
            else:
                raise
        self.model_name = model

        # First run in auto mode: speed-benchmark base.en, upgrade if in budget.
        if self.settings.model == "auto" and not self.settings.tiered_model:
            self._auto_tier(device)

        self.recorder = Recorder(pre_roll_seconds=self.settings.pre_roll_seconds)
        self.hotkey = PushToTalk(on_start=self._on_start, on_stop=self._on_stop,
                                 combo=self.settings.hotkey_combo)
        self.tray: "Tray | None" = None
        self.overlay = None
        if self.settings.show_overlay:
            try:
                from localflow.overlay import Overlay
                self.overlay = Overlay()
            except Exception:
                log.exception("Overlay unavailable")
        vocab.ensure_file()
        self.history: deque[tuple[str, str]] = deque(maxlen=5)  # (time, text)
        # Take state: 'idle' | 'holding' (combo down) | 'auto' (tap, VAD-stopped)
        self._take_state = "idle"
        self._take_lock = threading.Lock()
        self._pressed_at = 0.0

        self.cleaner = None
        if self.settings.llm_cleanup:
            self._load_cleaner()

    def _auto_tier(self, device: str) -> None:
        from localflow.tiering import benchmark_base_seconds, decide_upgrade

        secs = benchmark_base_seconds(self.transcriber.model)
        upgrade = decide_upgrade(secs, device)
        log.info("Tier benchmark: base took %.2fs for 5s audio -> %s",
                 secs, upgrade or "stay on base")
        if upgrade:
            # decide_upgrade names the English variant; a German/auto user
            # needs the multilingual one (small, not small.en).
            upgrade = model_for_language(upgrade, self.settings.language)
            try:
                self.transcriber = Transcriber(
                    model_name=upgrade, device=device,
                    language_hint=self.settings.language_hint)
                self.model_name = upgrade
            except Exception:
                log.exception("Upgrade to %s failed (offline?); keeping %s",
                              upgrade, self.model_name)
        self.settings.tiered_model = self.model_name
        config.save(self.settings)

    def _load_cleaner(self) -> None:
        try:
            from localflow.cleanup import Cleaner
            self.cleaner = Cleaner(timeout=self.settings.cleanup_timeout)
            self.cleaner.warm_up(lang=self.settings.language)
        except Exception:
            log.exception("Cleanup LLM unavailable; raw transcripts only")
            self.cleaner = None

    def _set_language(self, lang: str) -> None:
        """Switch language; reloads the whisper model in the background if needed."""
        self.settings.language = lang
        config.save(self.settings)
        size = self.settings.tiered_model or self.model_name
        new_model = model_for_language(size, lang)
        if new_model == self.model_name:
            return

        def reload() -> None:
            try:
                t = Transcriber(model_name=new_model,
                                language_hint=self.settings.language_hint)
                t.warm_up()
                self.transcriber = t  # atomic swap; old model keeps serving until now
                self.model_name = new_model
                log.info("Switched to %s for language %r", new_model, lang)
            except Exception:
                log.exception("Could not load %s (offline?); keeping %s",
                              new_model, self.model_name)

        threading.Thread(target=reload, daemon=True).start()

    def _on_toggle_cleanup(self, enabled: bool) -> None:
        if enabled and self.cleaner is None:
            threading.Thread(target=self._load_cleaner, daemon=True).start()
        log.info("AI cleanup %s", "enabled" if enabled else "disabled")

    def _on_start(self) -> None:
        """Combo pressed: start a take — or stop the running tap-mode take."""
        with self._take_lock:
            if self._take_state == "auto":  # second tap = manual stop
                self._finalize_locked()
                return
            if self._take_state != "idle":
                return
            self._take_state = "holding"
            self._pressed_at = time.monotonic()
        log.info("Recording...")
        self.recorder.start()
        if self.settings.sound_feedback:
            sounds.play_start()
        if self.tray:
            self.tray.set_recording(True)
        if self.overlay:
            self.overlay.set_state("recording")
        threading.Thread(target=self._session_loop, daemon=True).start()

    def _on_stop(self) -> None:
        """Combo released: quick tap → keep recording (auto-stop); hold → done."""
        with self._take_lock:
            if self._take_state != "holding":
                return
            if time.monotonic() - self._pressed_at < TAP_SECONDS:
                self._take_state = "auto"  # tap: hands-free, VAD will stop it
                log.info("Tap mode: recording until %.1fs of silence "
                         "(or tap again)", self.settings.auto_stop_silence)
                return
            self._finalize_locked()

    def _session_loop(self) -> None:
        """Per-take worker: feeds the overlay; auto-stops tap-mode takes."""
        while self.recorder.recording:
            if self.overlay:
                self.overlay.feed_level(self.recorder.level)
            with self._take_lock:
                if self._take_state == "auto":
                    silent = (self.recorder.speech_seen and
                              self.recorder.silence_seconds()
                              >= self.settings.auto_stop_silence)
                    no_speech = (not self.recorder.speech_seen and
                                 self.recorder.take_seconds() > 10)
                    too_long = (self.recorder.take_seconds()
                                >= self.settings.max_take_seconds)
                    if silent or no_speech or too_long:
                        self._finalize_locked()
                        return
                elif self._take_state == "idle":
                    return
            time.sleep(0.05)

    def _finalize_locked(self) -> None:
        """End the take and hand off to processing. Caller holds _take_lock."""
        self._take_state = "idle"
        released_at = time.perf_counter()
        audio = self.recorder.stop()
        if self.settings.sound_feedback:
            sounds.play_stop()
        if self.tray:
            self.tray.set_recording(False)
        duration = audio.size / 16_000
        if duration < MIN_AUDIO_SECONDS or not self.recorder.speech_seen:
            log.info("Too short or no speech (%.2fs), ignoring", duration)
            if self.overlay:
                self.overlay.set_state("hidden")
            return
        if self.overlay:
            self.overlay.set_state("processing")
        # Off the listener thread so the hotkey stays responsive.
        threading.Thread(target=self._process, args=(audio, released_at),
                         daemon=True).start()

    def _process(self, audio, released_at: float) -> None:
        try:
            text = self.transcriber.transcribe(
                audio, language=self.settings.language, hotwords=vocab.hotwords(),
                allowed_languages=self.settings.auto_languages)
            if not text:
                log.info("No speech detected")
                return
            if self.settings.llm_cleanup and self.cleaner is not None:
                text = self.cleaner.clean(text, lang=self.transcriber.last_language)
            inject_text(text)
            self.history.appendleft((time.strftime("%H:%M"), text))
            if self.tray:
                self.tray.refresh()
            # Remember the session's dominant language across restarts.
            if self.settings.language == "auto":
                dominant = self.transcriber.dominant_language()
                if dominant and dominant != self.settings.language_hint:
                    self.settings.language_hint = dominant
                    config.save(self.settings)
            log.info("End-to-end latency (release -> paste): %.2fs",
                     time.perf_counter() - released_at)
        except Exception:
            log.exception("Dictation failed")
        finally:
            if self.overlay:
                self.overlay.set_state("hidden")

    def run(self) -> None:
        self.transcriber.warm_up()
        self.recorder.open()  # always-on stream feeds the pre-roll buffer
        self.hotkey.start()
        log.info("LocalFlow ready. Hold %s, speak, release.", self.settings.hotkey)

        try:
            from localflow.tray import Tray
            self.tray = Tray(self.settings, status=self.model_name,
                             on_toggle_cleanup=self._on_toggle_cleanup,
                             on_set_language=self._set_language,
                             on_quit=self._shutdown,
                             history=self.history,
                             on_open_vocab=vocab.open_in_editor)
            self.tray.run()  # blocks until Quit
        except Exception:
            log.exception("Tray unavailable, running headless (Ctrl+C to quit)")
            try:
                self.hotkey.join()
            except KeyboardInterrupt:
                self._shutdown()

    def _shutdown(self) -> None:
        self.hotkey.stop()
        self.recorder.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from localflow.singleinstance import acquire
    if not acquire():
        log.warning("LocalFlow is already running; exiting this instance.")
        return
    LocalFlowApp().run()
