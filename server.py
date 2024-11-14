from fastapi import FastAPI, Request, Response
import httpx
import asyncio

app = FastAPI()

# Target server to which requests will be proxied
TARGET_SERVER = "http://live1.nokia.tivo.com"

# Audio Delaying
audio_delay_enabled = False

# Track session start, segment requests, and playlist stick simulation
session_started = False
segment_count = 0
delay_after_segments = 3  # Delay after this many segments
delay_duration = 10  # Delay duration in seconds
is_delaying = False

# Stuck playlist simulation variables
is_stuck_playlist_enabled = True
playlist_request_count = 0
playlist_stick_threshold = 10  # Number of requests after which the playlist will "stick"
cached_playlist_content = None
is_playlist_stuck = False

# Recovery settings
stuck_recovery_timeout = 60  # Time in seconds after which the stuck condition is reset


# Function to handle stuck playlist logic
async def handle_stuck_playlist(request: Request):
    global playlist_request_count, is_playlist_stuck, cached_playlist_content

    playlist_request_count += 1
    print(f"Playlist request count: {playlist_request_count}")

    # Trigger the stuck playlist condition after a threshold
    if is_stuck_playlist_enabled and playlist_request_count > playlist_stick_threshold:
        is_playlist_stuck = True

        # Cache the playlist content on the first request that triggers the stuck condition
        if cached_playlist_content is not None:
            print("Serving cached playlist to simulate stuck playlist.")
            return Response(
                content=cached_playlist_content,
                media_type="application/vnd.apple.mpegurl" if ".m3u8" in request.url.path else "application/dash+xml"
            )

        # Start the recovery timer if stuck condition is first triggered
        if cached_playlist_content is None:
            print("Stuck playlist detected. Starting recovery timer...")
            asyncio.create_task(reset_stuck_playlist())

    return None  # Continue normal processing if not stuck


# Function to reset the stuck playlist state
async def reset_stuck_playlist():
    global is_playlist_stuck, playlist_request_count, cached_playlist_content
    await asyncio.sleep(stuck_recovery_timeout)
    if is_playlist_stuck:
        print("Recovering from stuck playlist state after timeout.")
        is_playlist_stuck = False
        playlist_request_count = 0
        cached_playlist_content = None


# Function to handle audio delay logic
async def handle_audio_delay(request: Request):
    global segment_count, is_delaying

    if session_started and "audio" in request.url.path:
        segment_count += 1
        print(f"Received {segment_count} audio segment request")

        if segment_count > delay_after_segments and not is_delaying:
            is_delaying = True
            print(f"Delaying response for {delay_duration} seconds...")
            await asyncio.sleep(delay_duration)
            is_delaying = False
            segment_count = 0  # Reset the segment count
            print("Resuming normal response streaming...")


# Proxy request function
async def proxy_request(request: Request):
    global session_started, cached_playlist_content

    # Complete URL on the target server, including query parameters
    target_url = f"{TARGET_SERVER}{request.url.path}?{request.url.query}"

    # Check if the request is for a playlist
    if ".m3u8" in request.url.path or ".mpd" in request.url.path:
        stuck_response = await handle_stuck_playlist(request)
        if stuck_response:
            return stuck_response

    # Proxy the request to the target server
    async with httpx.AsyncClient() as client:
        headers = {key: value for key, value in request.headers.items() if key.lower() != 'host'}
        async with client.stream(
            request.method,
            target_url,
            headers=headers,
            content=await request.body()
        ) as response:

            # Cache the playlist content if the stuck condition is triggered
            if is_playlist_stuck and cached_playlist_content is None:
                cached_playlist_content = await response.aread()
                print("Cached playlist content for stuck simulation.")

            # Handle audio delay logic if enabled
            if audio_delay_enabled:
                await handle_audio_delay(request)

            # Stream the response back to the client
            return Response(
                content=await response.aread(),
                headers=dict(response.headers),
                status_code=response.status_code
            )


# Route for handling all requests
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def catch_all(request: Request, path: str):
    global session_started
    if not session_started and (".m3u8" in request.url.path or ".mpd" in request.url.path):
        print("Session start detected:", request.url.path)
        session_started = True
    return await proxy_request(request)
