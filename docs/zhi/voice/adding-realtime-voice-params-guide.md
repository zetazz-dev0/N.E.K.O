# N.E.K.O. — Adding Realtime API Voice Parameters (Per-Provider)

> Lessons learned from adding OpenAI Realtime voice/speed/temperature/instructions
> to the character advanced settings. Use this as a reference when adding similar
> customization for Gemini, Qwen, Step, or any future Realtime provider.

---

## Architecture Overview

```
Character Config (characters.json)
  └─ per-character fields (e.g. realtime_speed, realtime_temperature, ...)
       │
       ▼
core.py  ── reads fields from character config ──▶  OmniRealtimeClient(...)
       │                                                  │
       │                                                  ▼
       │                                         omni_realtime_client.py
       │                                         └─ configure_session()
       │                                            └─ per-model session config
       │
       └─ also decides: use_tts = True/False
          (builtin voices skip external TTS)
```

## Files Involved (Touch Points)

| # | File | What to change |
|---|------|----------------|
| 1 | `static/js/chara_manager.js` | Add UI controls in advanced settings |
| 2 | `main_routers/characters_router.py` | Return builtin voice list from `/api/characters/voices` |
| 3 | `utils/config_manager.py` | Whitelist builtin voice IDs in `validate_voice_id()` |
| 4 | `main_logic/core.py` | Read params from character config, pass to client, handle TTS bypass |
| 5 | `main_logic/omni_realtime_client.py` | Accept new params in constructor, apply in session config |
| 6 | `config/api_providers.json` | (Only if adding a new provider — not needed for param additions) |

---

## Step-by-Step Guide

### 1. Define Builtin Voice List (Backend)

**`main_routers/characters_router.py`** — In the `get_voices()` endpoint:

```python
# Always return builtin voices; frontend filters by current Core API type
result["openai_voices"] = {
    "alloy": "Alloy (neutral)",
    "coral": "Coral (female)",
    # ...
}
# For Gemini, add:
result["gemini_voices"] = {
    "Leda": "Leda",
    # ...
}
```

### 2. Whitelist Voice IDs in Validation

**`utils/config_manager.py`** — In `validate_voice_id()`:

The save endpoint (`PUT /api/characters/catgirl/voice_id/{name}`) calls
`validate_voice_id()` which rejects any voice ID not in:
- CosyVoice voice_storage
- Free preset voices
- GPT-SoVITS custom voices

**You MUST add a whitelist** for builtin voice IDs, otherwise saving will fail
with `partialSaveVoiceFailed`:

```python
OPENAI_BUILTIN_VOICES = {
    'alloy', 'ash', 'ballad', 'coral', 'echo',
    'fable', 'marin', 'sage', 'shimmer', 'verse',
}
if voice_id in OPENAI_BUILTIN_VOICES:
    return True
```

> **Gotcha**: This was the most non-obvious failure. The error message
> (`character.partialSaveVoiceFailed`) comes from the frontend catching a 400
> response from the voice_id PUT endpoint. The character itself saves fine —
> only the voice_id update fails.

### 3. Frontend: Add Voice Options & Parameter Controls

**`static/js/chara_manager.js`** — Two areas to modify:

#### 3a. Voice Dropdown — `loadVoices()` function

The function fetches `/api/characters/voices` and populates the `<select>`.
Add a new `optgroup` conditionally based on `coreApiType`:

```javascript
// Fetch current Core API type first
const coreApiResp = await fetch('/api/config/core_api');
const coreApiData = await coreApiResp.json();
const coreApiType = coreApiData.coreApi || '';

// Then conditionally show the right voice group
if (coreApiType === 'openai' && data.openai_voices) {
    const group = document.createElement('optgroup');
    group.label = '── OpenAI Realtime ──';
    // ... populate options
    select.appendChild(group);
} else if (coreApiType === 'gemini' && data.gemini_voices) {
    // ... similar
} else if (data.free_voices) {
    // ... free preset voices (default)
}
```

> **Important**: The original code had a backend condition that only returned
> `free_voices` when `IS_FREE_VERSION` was true AND URL contained `lanlan.tech`.
> We changed this to always return all voice lists, letting the frontend filter.
> This is cleaner and avoids state issues when running from source.

#### 3b. Parameter Controls — In `showCatgirlForm()` after voice section

Create input elements inside the `foldContent` (advanced settings fold).
Wrap them in a container div with an ID for visibility toggling:

```javascript
const realtimeSettingsWrapper = document.createElement('div');
realtimeSettingsWrapper.id = 'realtime-settings-wrapper';
realtimeSettingsWrapper.style.display = 'none'; // hidden by default

// Speed input: <input type="number" name="realtime_speed" min="0.7" max="1.3" step="0.1">
// Temperature input: <input type="number" name="realtime_temperature" min="0" max="1.2" step="0.1">
// Instructions textarea: <textarea name="realtime_instructions">

foldContent.appendChild(realtimeSettingsWrapper);
```

Then in `loadVoices()`, toggle visibility:
```javascript
const wrapper = form.querySelector('#realtime-settings-wrapper');
if (wrapper) wrapper.style.display = (coreApiType === 'openai') ? '' : 'none';
```

> **Key pattern**: Use `name="realtime_speed"` etc. on form elements. The form
> submission collects all named fields via `FormData` and POSTs as JSON. The
> backend `update_catgirl` endpoint stores them as top-level character fields.
> No need to use `_reserved` — these are NOT reserved fields.

### 4. Backend: Read Params & Pass to Client

**`main_logic/core.py`** — Two places where `OmniRealtimeClient` is created:
1. `start_session()` → `new_session = OmniRealtimeClient(...)`
2. Hot-swap path → `self.pending_session = OmniRealtimeClient(...)`

Both must read from character config and pass params:

```python
_cat_cfg = self.lanlan_basic_config.get(self.lanlan_name, {})
new_session = OmniRealtimeClient(
    # ... existing params ...
    realtime_speed=float(_cat_cfg['realtime_speed']) if _cat_cfg.get('realtime_speed') else None,
    realtime_temperature=float(_cat_cfg['realtime_temperature']) if _cat_cfg.get('realtime_temperature') else None,
    realtime_instructions=_cat_cfg.get('realtime_instructions') or None,
)
```

> **Pattern**: Use `None` as default → the client falls back to its own defaults.
> Parse strings to float since character config stores everything as strings.

### 5. Client: Accept & Apply Params

**`main_logic/omni_realtime_client.py`**:

Add params to `__init__`:
```python
def __init__(self, ..., realtime_speed=None, realtime_temperature=None, realtime_instructions=None):
    self.realtime_speed = realtime_speed
    self.realtime_temperature = realtime_temperature
    self.realtime_instructions = realtime_instructions
```

Apply in `configure_session()` under the model-specific branch:
```python
elif "gpt" in self.model:
    await self.update_session({
        "temperature": self.realtime_temperature if self.realtime_temperature is not None else 0.8,
        "audio": {
            "output": {
                "voice": self.voice if self.voice else "marin",
                "speed": self.realtime_speed if self.realtime_speed is not None else 1.0
            }
        }
    })
```

### 6. TTS Bypass for Builtin Voices

**`main_logic/core.py`** — This is critical and easy to miss.

The system has a `use_tts` flag. When a character has a non-empty `voice_id`,
the system assumes it's a custom CosyVoice voice and starts an external TTS
worker. Builtin Realtime voices (like OpenAI's `coral`) must **bypass** this.

Three changes needed:

#### 6a. Add a helper to identify builtin voices:
```python
OPENAI_BUILTIN_VOICES = frozenset({
    'alloy', 'ash', 'ballad', 'coral', 'echo',
    'fable', 'marin', 'sage', 'shimmer', 'verse',
})

def _is_realtime_builtin_voice(self, voice_id):
    return bool(voice_id) and voice_id in self.OPENAI_BUILTIN_VOICES
```

#### 6b. Skip TTS in `start_session()`:
```python
elif self._is_realtime_builtin_voice(self.voice_id):
    self.use_tts = False  # use native realtime audio output
```

#### 6c. Exclude from `has_custom_tts` checks (two locations):
```python
has_custom_tts = (
    bool(self.voice_id)
    and not self._is_free_preset_voice
    and not self._is_realtime_builtin_voice(self.voice_id)  # <-- add this
) or (...)
```

> **Gotcha**: Without this, the system tries to start a CosyVoice TTS worker
> for voice IDs like "coral", which fails silently and produces no audio output.

---

## Adding a New Provider (e.g., Gemini)

When adding Gemini-specific voice params, follow the same pattern:

1. **Voices**: Add `gemini_voices` to the `/api/characters/voices` response
2. **Whitelist**: Add Gemini voice names to `validate_voice_id()`
3. **Frontend**: Add conditional `optgroup` for `coreApiType === 'gemini'`
4. **Frontend**: Add Gemini-specific param fields (e.g., `gemini_speed`) with
   visibility toggled by `coreApiType === 'gemini'`
5. **Backend**: Read `gemini_*` fields from character config, pass to client
6. **Client**: Apply in the `elif "gemini" in self.model:` branch of
   `configure_session()`
7. **TTS bypass**: Add Gemini builtin voice IDs to `_is_realtime_builtin_voice()`

### Gemini-Specific Notes

Gemini Live uses Google's SDK (`google.genai`) instead of WebSocket directly.
Voice config is set via:
```python
voice_config=types.VoiceConfig(
    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Leda")
)
```
This is in `configure_session()` under the Gemini branch. The param names and
structure differ from OpenAI's — check Google's Gemini Live API docs.

---

## Common Pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| `partialSaveVoiceFailed` on save | Voice ID not in whitelist | Add to `validate_voice_id()` |
| No audio after selecting builtin voice | `use_tts=True` triggers external TTS | Add to `_is_realtime_builtin_voice()` |
| Dropdown empty after code change | Browser cached old JS | `Cmd+Shift+R` to hard refresh |
| Voice options not showing | Code outside `if (select && data.voices)` block | Keep all select operations inside the block |
| Free voices not showing from source | Backend condition checks `IS_FREE_VERSION` + `lanlan.tech` | Return all voice lists unconditionally |
| Params not taking effect | Only one of two `OmniRealtimeClient()` call sites updated | Always update BOTH: `new_session` and `pending_session` |

---

## Data Flow Summary

```
[Web UI] ─── form fields (name="realtime_speed" etc.) ───▶ [FormData]
    │                                                           │
    │  POST /api/characters/catgirl/{name}                      │
    │  (regular fields pass through _filter_mutable_catgirl_fields)
    │                                                           │
    ▼                                                           ▼
[characters.json]  ◀── config_manager.save_characters() ── [update_catgirl()]
    │
    │  config_manager.get_character_data()
    │  → lanlan_basic_config[name]['realtime_speed']
    │
    ▼
[core.py] ── float(cat_cfg['realtime_speed']) ──▶ OmniRealtimeClient(realtime_speed=...)
                                                        │
                                                        ▼
                                                 [configure_session()]
                                                 └─ "speed": self.realtime_speed or 1.0
```
