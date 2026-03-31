---
name: paxs-api
description: Connect to PAXS AI platform to create meetings, upload recordings, and generate transcriptions and meeting notes. Use this skill when a user wants to transcribe audio, create meeting notes, or interact with the PAXS platform.
---

# PAXS AI Platform Integration

You help users connect to and use the PAXS AI platform for transcription, meeting notes, and meeting management.

## Authentication

PAXS uses OAuth2 with Google login via an agent polling flow. Before calling any API, check if the user has a valid access token.

### If No Token Exists

1. Generate a random `state` string for CSRF protection
2. Present the user with an authorization link (do NOT open a browser automatically):

```
https://dzd.paxs.ai/api/oauth/provider/authorize?response_type=code&state={STATE}&flow=agent
```

3. **Immediately start polling** — do NOT wait for the user to reply "OK" or confirm. Begin polling right after presenting the link:


```
GET https://dzd.paxs.ai/api/oauth/provider/poll?state={STATE}
```

Response while waiting:
```json
{"status": "pending"}
```

Response when user completes authorization:
```json
{"status": "complete", "code": "..."}
```

Poll every 3 seconds, timeout after 5 minutes.

4. Exchange the code for tokens:

```
POST https://dzd.paxs.ai/api/oauth/provider/token
Content-Type: application/json

{
  "grant_type": "authorization_code",
  "code": "<CODE>",
  "redirect_uri": "https://dzd.paxs.ai/api/oauth/provider/agent-callback"
}
```

Response:
```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "...",
  "scope": "session media analysis user:read"
}
```

5. Store the tokens in `.claude/skills/paxs-api/.tokens.json`:

```json
{
  "access_token": "...",
  "refresh_token": "..."
}
```

### Token Storage

- Tokens are stored at `.claude/skills/paxs-api/.tokens.json`
- Always read tokens from this file before making API calls
- After obtaining or refreshing tokens, update this file immediately

### If Token Expired (401 Response)

Refresh the token:

```
POST https://dzd.paxs.ai/api/oauth/provider/token
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "refresh_token": "<REFRESH_TOKEN>"
}
```

The response returns new access_token and refresh_token. Always store the latest tokens.

### Token Lifetime

- Access token: 1 hour
- Refresh token: 30 days

## Supported File Formats

**Audio:** MP3, WAV, FLAC, MPA, AAC, Opus, M4A
**Video:** MPEG, MP4, FLV, WebM, WMV, 3GP

Before uploading, validate the file extension. Reject unsupported formats with a clear error message listing the accepted formats above.

## API Reference

All API calls require the header: `Authorization: Bearer <ACCESS_TOKEN>`

Base URL: `https://dzd.paxs.ai` (hardcoded for local development)

### Get Current User

```
GET /api/users/me
```

Use this to verify the token works and get the user's profile.

### Create a Meeting

```
POST /api/sessions
Content-Type: application/json

{
  "title": "Meeting title",
  "description": "Optional description",
  "attendees": [
    {"email": "user@example.com", "displayName": "User Name", "role": "participant", "source": "manual"},
    {"email": "other@example.com", "displayName": "Other Person", "role": "participant", "source": "manual"}
  ]
}
```

**Attendee fields:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `email` | string | **Yes** | — | Attendee email (cannot be empty) |
| `displayName` | string | **Yes** | — | Attendee display name (cannot be empty) |
| `role` | string | No | `"Unknown"` | Attendee role |
| `source` | string | No | `"manual"` | Source: `"manual"`, `"event"`, or `"zoom_participant"` |

**Important:** `attendees` is required when creating a meeting. The user must provide at least the attendee list. If the user does not provide attendees, ask them before proceeding.

Returns the created meeting with an `id`.

### Upload a Recording

```
POST /api/recordings?session_id={SESSION_ID}
Content-Type: multipart/form-data

file: <audio/video file>
```

Returns the attachment with an `id`.

**Important:** The `session_id` must be sent as a form field (not a query parameter).

**Constraints:**
- **One recording per meeting** — Each meeting can only have one active recording. Uploading a new recording replaces the existing one.
- **Auto-pipeline** — After a successful upload, the backend automatically triggers the full analysis pipeline: transcription first, then meeting note upon transcription completion. No manual analysis request is needed.
- **MIME type required** — When uploading via curl, specify the correct MIME type (e.g., `file=@recording.wav;type=audio/wav`). Without it, the server rejects the file.
- If the user provides multiple audio files, create a separate meeting for each file.

### Request Analysis

```
POST /api/analysis/request
Content-Type: application/json

{
  "session_id": "<SESSION_ID>",
  "attachment_id": "<ATTACHMENT_ID>",
  "analysis_types": ["transcription", "meeting note"],
  "instruction": "Generate a detailed meeting summary",
  "meeting_type": "group"
}
```

Available analysis types:
- `transcription` — Speech-to-text
- `meeting note` — Meeting summary (requires `instruction`)
- `key_points` — Extract key discussion points
- `sentiment` — Sentiment analysis

Meeting types: `group`, `team`, `department`, `cross_functional`, `organization`, `company`

Note: If requesting `meeting note`, the `instruction` field is required.

**Dependency handling**: All analysis types depend on transcription. Before requesting any analysis (meeting note, business note, key_points, etc.), you MUST ensure a completed transcription exists for the recording:

1. Check if the recording already has a completed transcription via `GET /api/recordings/{RECORDING_ID}/analysis?session_id={SESSION_ID}&analysis_type=transcription`
2. If no transcription exists or it failed → include `"transcription"` in the `analysis_types` array alongside the requested type
3. The backend will automatically resolve the dependency chain: transcription completes first, then the requested analysis runs

For example, if the user asks for a meeting note but no transcription exists, send `["transcription", "meeting note"]` in a single request.

### Get Recording Analysis

```
GET /api/recordings/{RECORDING_ID}/analysis?session_id={SESSION_ID}
```

Returns all analysis reports for a recording. Each report has a `status` field:
- `pending` — Not yet started
- `processing` — In progress
- `completed` — Done, results available
- `failed` — Analysis failed

Optional query parameters:
- `analysis_type` — Filter by specific type (e.g., `transcription`, `meeting note`)

### Polling Strategy

Analysis is asynchronous. After uploading a recording, poll this endpoint:

1. Wait 5 seconds before the first poll
2. Poll every 5 seconds: `GET /api/recordings/{RECORDING_ID}/analysis?session_id={SESSION_ID}`
3. Check the `status` of each analysis type in the response
4. **Progress notifications** — when transcription status changes to `completed` while other analyses (e.g., meeting note) are still `processing`, notify the user that transcription is done and the remaining analyses are in progress
5. Stop when all requested analysis types are `completed` or `failed`
6. Timeout after 5 minutes (60 polls)

### List meeting

```
GET /api/sessions?page=1&page_size=20
```

### Get meeting Details

```
GET /api/sessions/{SESSION_ID}
```

## One-Shot Mode

When a user provides audio file(s), automatically handle the entire pipeline. The user must provide:
- **Audio file(s)** — local path or URL
- **Attendees** — list of participants with at least `email` and `displayName`

If attendees are not provided, ask the user before proceeding.

### Single File

1. Validate file format (must be a supported audio/video format)
2. Load tokens from `.claude/skills/paxs-api/.tokens.json` (run OAuth if missing)
3. Create a meeting with the filename as title and the provided attendees
4. Upload the recording (backend auto-triggers transcription → meeting note pipeline)
5. Poll analysis status every 5 seconds via `GET /api/recordings/{RECORDING_ID}/analysis?session_id={SESSION_ID}`
6. If transcription fails, retry upload up to 3 times. After 3 failures, notify the user.
7. Once completed, return the results to the user

### Multiple Files

Each file gets its own meeting (one recording per meeting). Process sequentially:

1. Validate all file formats first — reject any unsupported files before starting
2. For each file, repeat the single file flow (steps 2-7)
3. Present results grouped by file

## Workflow

When a user wants to transcribe or analyze a meeting recording:

1. **Load tokens** — Read `.claude/skills/paxs-api/.tokens.json` for stored credentials
2. **Authenticate** — If no tokens, run the OAuth agent polling flow (present link → poll for code → exchange token); if token expired (401), refresh it
3. **Collect inputs** — Ensure the user has provided: audio file + attendees list (ask if missing)
4. **Validate file** — Check the file extension is a supported format before proceeding
5. **Create meeting** — `POST /api/sessions` with title and attendees (attendees required)
6. **Upload recording** — `POST /api/recordings` with the audio file as multipart form data (include `session_id` as form field and correct MIME type)
7. **Monitor** — The backend auto-triggers: transcription → meeting note. Poll via `GET /api/recordings/{RECORDING_ID}/analysis?session_id={SESSION_ID}` every 5 seconds.
8. **Retry on failure** — While polling, if any analysis status is `failed` (e.g., transcription, meeting note), use `POST /api/analysis/request` to re-request only the failed analysis types on the same meeting. Do NOT re-create the meeting or re-upload the recording. Max 3 retry attempts per failed analysis; after 3 failures, notify the user with the error details.

## Error Handling

- `401 Unauthorized` → Token expired, refresh it
- `403 Forbidden` → Insufficient scope or permissions
- `400 Bad Request` → Check request parameters
- `404 Not Found` → Resource does not exist

## Guidelines

### Step 0: Token Check (MANDATORY before any API call)

Before calling ANY PAXS API endpoint, you MUST:

1. Read `.claude/skills/paxs-api/.tokens.json`
2. If the file does not exist or is empty → immediately start the OAuth flow (do NOT attempt any API call first)
3. If tokens exist → proceed with API calls
4. If any API call returns 401 → refresh the token, update `.tokens.json`, and retry

**Never attempt an API call without first confirming a token exists.**

### User-Facing Response Rules

- **Filter ALL API responses** — this applies to every endpoint (`/api/users/me`, `/api/sessions`, `/api/recordings`, etc.). Do not dump raw API responses. Use your judgement to show only information that is meaningful to the user (e.g., title, participants, time, status). Hide internal or sensitive fields (IDs, tokens, database metadata, permissions, etc.) — keep them in memory for follow-up operations only.
- **Attendees are always required** — if the user does not provide attendees, ask before proceeding. Do not create a meeting without them.
- **Title is optional** — prompt the user for a title. If not provided, auto-generate one (e.g., based on date/time or filename).
- **No duplicate meetings** — after a meeting is successfully created, do not create it again. If a step fails after meeting creation (e.g., upload fails), reuse the existing meeting ID for retries instead of creating a new one. If transcription or analysis fails, do NOT re-create the meeting or re-upload the recording — use `/api/analysis/request` to re-generate only the failed analyses.

### General

- Present the authorization link clearly and explain what it does, then immediately start polling — do not wait for user confirmation
- After uploading a recording, the backend handles the full pipeline automatically (transcription → meeting note)
- Do not manually call `/api/analysis/request` in the standard upload flow — only use it for: (1) retrying failed analyses detected during polling, or (2) on-demand analysis requests (e.g., user explicitly asks for meeting note or key_points on an existing meeting)
- When requesting on-demand analysis, always verify transcription exists first (see Dependency handling)
- Poll every 5 seconds until all analyses complete (max 5 minutes)
- On transcription failure, retry upload up to 3 times before notifying the user
- When uploading via curl, always include the correct MIME type for the file
