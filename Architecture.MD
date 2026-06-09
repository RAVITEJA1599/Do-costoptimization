                              ┌──────────────┐
                              │     USER     │
                              └──────┬───────┘
                                     │
                                     ▼
                           ┌───────────────────┐
                           │  REACT FRONTEND   │
                           └────────┬──────────┘
                                    :
                                    : Login / Signup
                                    ▼
                           ┌───────────────────┐
                           │  PYTHON BACKEND   │
                           │    (FastAPI)      │
                           │                   │
                           │  · Custom JWT Auth│
                           └───┬───────┬───┬───┘
                               :       :   :
                ┌──────────────┘       :   └──────────────┐
                :                      :                  :
                ▼                      ▼                  ▼
      ┌─────────────────┐     ┌──────────────┐    ┌──────────────┐
      │ DIGITALOCEAN API│     │   FASTAPI    │    │    CLAUDE    │
      │                 │     │  WEBSOCKET   │    │     API      │
      │ Projects        │     │  (Progress)  │    │ Cost Analysis│
      │ Droplets        │     └──────┬───────┘    └──────┬───────┘
      │ Volumes         │            :                   :
      │ Databases       │            : Live Updates      :
      │ Snapshots       │            ▼                   :
      │ Load Balancers  │    ┌───────────────┐           :
      └──────┬──────────┘    │    REACT      │           :
             :               │  (Progress    │           :
             ▼               │   Tracker)    │           :
      ┌─────────────────┐    └───────────────┘           :
      │  DIGITALOCEAN   │                                :
      │    PROJECT      │                                :
      └─────────────────┘                                :
                                                         ▼
                                                ┌──────────────┐
                                                │ POSTGRESQL   │
                                                │  (Docker)    │
                                                │              │
                                                │ · users      │
                                                │ · analyses   │
                                                └──────┬───────┘
                                                       :
                                                       : Stored Results
                                                       ▼
                                                ┌───────────────┐
                                                │    REACT      │
                                                │ Final Report  │
                                                │ Suggestions   │
                                                │ Fix Steps     │
                                                └───────────────┘
