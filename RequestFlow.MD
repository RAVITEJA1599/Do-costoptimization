## AI Cloud Cost Detective - Request Flow

```
① User ─·─·─► React ─·─·─► FastAPI Auth ─·─·─► JWT (PostgreSQL)

② User selects a DigitalOcean Project ─·─·─► Python Backend

③ Python ─·─·─► DigitalOcean API / doctl ─·─·─► Fetches all resources

④ Python ─·─·─► FastAPI WebSocket ─·─·─► React (Live Progress)

⑤ Python ─·─·─► Claude API ─·─·─► Cost Analysis

⑥ Python ─·─·─► PostgreSQL ─·─·─► Stores Analysis History

⑦ React ◄·─·─·─ Final Report with Recommendations & Fix Steps
