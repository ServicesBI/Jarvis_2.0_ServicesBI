"""Find and open first relevant YouTube video directly.
Searches YouTube, finds the best matching video ID, opens it.
Usage: python youtube-play.py "search query"
"""
import sys, urllib.request, re, json, subprocess

query = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'lofi hip hop'
encoded = urllib.parse.quote(query)

try:
    url = f'https://www.youtube.com/results?search_query={encoded}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    req = urllib.request.Request(url, headers=headers)
    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')

    # Extract video data: look for videoRenderer blocks (real search results, not ads)
    # Ads use "promotedVideoRenderer", real results use "videoRenderer"
    # Find all videoRenderer video IDs
    results = re.findall(r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"', html)

    # Also get titles to match relevance
    titles = re.findall(r'"videoRenderer":\{"videoId":"[^"]+","thumbnail".*?"title":\{"runs":\[\{"text":"([^"]+)"\}', html)

    if not results:
        # Fallback: get any video IDs (less precise)
        results = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
        # Remove duplicates
        seen = set()
        unique = []
        for vid in results:
            if vid not in seen:
                seen.add(vid)
                unique.append(vid)
                if len(unique) >= 5:
                    break
        results = unique

    if results:
        video_id = results[0]  # First real search result (not ad)
        video_url = f'https://www.youtube.com/watch?v={video_id}'
        subprocess.run(['cmd', '/c', 'start', '', video_url], shell=True, timeout=5)
        title = titles[0] if titles else 'unknown'
        print(json.dumps({"status": "playing", "video_id": video_id, "title": title, "url": video_url}))
    else:
        # No results found — open search page
        subprocess.run(['cmd', '/c', 'start', '', url], shell=True, timeout=5)
        print(json.dumps({"status": "search_fallback"}))

except Exception as e:
    # Fallback: open search
    fallback = f'https://www.youtube.com/results?search_query={encoded}'
    subprocess.run(['cmd', '/c', 'start', '', fallback], shell=True, timeout=5)
    print(json.dumps({"status": "error", "message": str(e)[:200]}))
