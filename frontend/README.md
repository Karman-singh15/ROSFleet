# ROSFleet frontend

Next.js 15 (App Router) + TypeScript + Tailwind v4.

```bash
npm install
cp .env.example .env.local      # point it at your backend
npm run dev                     # http://localhost:3000
```

The backend must allow this origin. It defaults to allowing port 3000; for
anything else, set `CORS_ORIGINS` on the backend:

```bash
CORS_ORIGINS='["http://localhost:3100"]' uvicorn app.main:app --port 8000
```

## Pages

| Route | What it does |
|---|---|
| `/` | Dashboard: fleet status, active missions, recent history |
| `/robots` | Register robots; fleet table |
| `/robots/[id]` | One robot: telemetry, current mission, history, stop button |
| `/maps` | Floor plan; **click the map to place a named destination** |
| `/missions` | Deploy a mission; live progress for all missions |
| `/missions/[id]` | One mission with its timestamped log |
| `/analytics` | Success rate, durations, utilisation, failure causes |

## The rule this code follows

**The frontend never talks to ROS.** It talks to the backend over REST and a
WebSocket, in the application's own vocabulary — robots, destinations,
missions. There is no `roslibpy`, no `/cmd_vel`, no topic anywhere in `src/`.

That separation is what lets the ROS side be restructured without touching a
line of React, and it is why the site still renders sensibly with the robot
switched off.

`src/lib/api.ts` is the only file that performs network calls.

## Notes

- **Live updates** come over `/ws`, with polling underneath as a safety net.
  A dashboard that silently freezes when a socket drops is worse than one
  that is three seconds stale.
- **Tailwind v4**: colours are declared in `@theme` in `globals.css`, which
  generates real utilities (`bg-panel`, `text-ink-dim`). Do **not** write the
  v3 bracket form `bg-[--color-panel]` — it compiles to nothing, silently.
- **Map coordinates**: ROS maps have +Y up with the origin at a world point;
  images have +row down from the top-left. `MapView.tsx` handles the flip.
  Get it wrong and the map renders vertically mirrored.
