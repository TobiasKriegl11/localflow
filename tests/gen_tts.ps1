param([string]$OutDir)
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
# 16kHz, 16-bit, mono to match app pipeline
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)

$de = @(
  "Hallo, ich heiße Tobias und ich wohne in München.",
  "Das Wetter ist heute wirklich schön und die Sonne scheint.",
  "Kannst du mir bitte sagen, wann der nächste Zug fährt?",
  "Ich habe gestern einen langen Spaziergang im Wald gemacht.",
  "Wir treffen uns morgen um drei Uhr am Bahnhof.",
  "Das ist eine gute Idee, aber ich bin mir nicht sicher.",
  "Vielen Dank für deine Hilfe, das war sehr nett von dir.",
  "Ja.",
  "Nein, danke.",
  "Guten Morgen zusammen.",
  "Ich muss noch schnell einkaufen gehen.",
  "Der Termin wurde leider auf nächste Woche verschoben."
)
$en = @(
  "Hello, my name is Tobias and I live in Munich.",
  "The weather is really nice today and the sun is shining.",
  "Can you please tell me when the next train leaves?",
  "I went for a long walk in the forest yesterday.",
  "Let us meet tomorrow at three o'clock at the station.",
  "That is a good idea, but I am not entirely sure.",
  "Thank you so much for your help, that was very kind of you.",
  "Yes.",
  "No, thanks.",
  "Good morning everyone.",
  "I still need to quickly go shopping.",
  "The meeting was unfortunately moved to next week."
)

function Speak($voice, $text, $path) {
  $syn.SelectVoice($voice)
  $syn.SetOutputToWaveFile($path, $fmt)
  $syn.Speak($text)
  $syn.SetOutputToNull()
}

for ($i=0; $i -lt $de.Count; $i++) {
  Speak "Microsoft Hedda Desktop" $de[$i] (Join-Path $OutDir ("de_{0:00}.wav" -f $i))
}
for ($i=0; $i -lt $en.Count; $i++) {
  Speak "Microsoft Zira Desktop" $en[$i] (Join-Path $OutDir ("en_{0:00}.wav" -f $i))
}
Write-Output "done"
