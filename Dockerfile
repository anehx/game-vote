# Crew game-vote — stdlib-only Python app, no build step needed.
FROM python:3.12-slim

WORKDIR /app

# Only two files make up the app.
COPY server.py index.html ./

# Listen on all interfaces inside the container, and keep the ballot
# file on a volume so votes survive container restarts/redeploys.
ENV HOST=0.0.0.0 \
    PORT=8787 \
    VOTES_FILE=/data/votes.json

VOLUME ["/data"]
EXPOSE 8787

CMD ["python3", "server.py"]
