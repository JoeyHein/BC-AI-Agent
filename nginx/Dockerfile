# Stage 1 — build the React/Vite frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2 — build the embeddable door designer widget
# Widget sources re-export DoorPreview / stampColumns / glassPockets from
# frontend/src, so that tree must be present next to widget/ (same relative
# paths as the git checkout).
FROM node:20-alpine AS widget-builder
WORKDIR /app
COPY widget/package*.json ./widget/
RUN cd widget && npm ci
COPY widget/ ./widget/
COPY frontend/src ./frontend/src
WORKDIR /app/widget
RUN npm run build

# Stage 3 — serve built files with Nginx
FROM nginx:1.27-alpine
COPY --from=frontend-builder /app/dist /usr/share/nginx/html
COPY --from=widget-builder /app/widget/dist/opendc-door-designer.iife.js /usr/share/nginx/html/widget/opendc-door-designer.iife.js
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
