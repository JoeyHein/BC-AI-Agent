# Stage 1 — build the React/Vite frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /src
COPY packages/door-renderer /src/packages/door-renderer
COPY frontend/package*.json /src/frontend/
WORKDIR /src/frontend
RUN npm ci
COPY frontend/ /src/frontend/
RUN npm run build

# Stage 2 — build the embeddable door designer widget
FROM node:20-alpine AS widget-builder
WORKDIR /src
COPY packages/door-renderer /src/packages/door-renderer
COPY widget/package*.json /src/widget/
WORKDIR /src/widget
RUN npm ci
COPY widget/ /src/widget/
RUN npm run build

# Stage 3 — serve built files with Nginx
FROM nginx:1.27-alpine
COPY --from=frontend-builder /src/frontend/dist /usr/share/nginx/html
COPY --from=widget-builder /src/widget/dist/opendc-door-designer.iife.js /usr/share/nginx/html/widget/opendc-door-designer.iife.js
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
