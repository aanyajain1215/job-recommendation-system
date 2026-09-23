# syntax=docker/dockerfile:1

FROM mirror.gcr.io/library/node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV WATCHPACK_POLLING=true
ENV CHOKIDAR_USEPOLLING=true

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["sh", "-c", "if [ ! -x node_modules/.bin/next ]; then npm ci; fi; npm run dev -- --hostname 0.0.0.0 --port 3000"]
