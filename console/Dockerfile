# Build the SPA, then serve the static bundle from nginx.
# The console is a pure static app — it discovers the gateway URL + admin key at
# runtime via the Setup screen, so there is no build-time backend coupling.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
