# myScriber

Local Whisper dictation in your Mac menubar. No API. No cost. No internet required.

## Install

```bash
bash install.sh
```

That's it. The script handles Homebrew, Python, ffmpeg, Whisper, icon generation, and drops **myScriber.app** into /Applications.

## First launch

Grant two permissions in System Settings when prompted:
- **Microphone** — to hear you
- **Accessibility** — to paste into any app (Chrome, Claude, Notes, Slack, anywhere)

## Usage

| | |
|---|---|
| Hold `Option+Space` | Record |
| Release | Transcribe + paste |
| Click mic icon | Settings / model switcher |

## Change hotkey or mode

Edit `~/.myscriber/config.json`:

```json
{
  "model": "base",
  "language": "auto",
  "hotkey": "option+space",
  "mode": "push_to_talk"
}
```

Restart myScriber after saving.

**Hotkeys:** `option+space` · `ctrl+space` · `f5` · `cmd+option+space`
**Modes:** `push_to_talk` · `toggle`

## Models

Click the mic icon in the menubar to switch:

| Model | Delay | Quality | Size |
|---|---|---|---|
| tiny | instant | decent | 40 MB |
| base | ~1 s | good ← default | 150 MB |
| small | ~2 s | better | 500 MB |
| medium | ~4 s | great | 1.5 GB |
| large-v3 | ~6 s | best | 3 GB |

M-series Macs use mlx-whisper automatically — noticeably faster.

## Logs

```bash
tail -f ~/.myscriber/myscriber.log
```
