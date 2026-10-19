# LectureKaki frontend

React, TypeScript, Vite, and React Router.

For a production build served by Nginx in Docker, see
[Docker setup](../docs/docker.md). The commands below run the Vite development
server with hot reload.

Run these commands from `frontend/` using Node.js 24 LTS:

```sh
npm ci
npm run dev
```

Checks: `npm run lint`, `npm run format:check`, `npm run typecheck`, and
`npm run build`. Run `npm run format` to apply Prettier formatting.
