# Stage 1 — build the React/Vite frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2 — build the embeddable door designer widget
FROM node:20-alpine AS widget-builder
WORKDIR /app
COPY widget/package*.json ./
RUN npm ci
COPY widget/ .
RUN npm run build

# Stage 3 — serve built files with Nginx
FROM nginx:1.27-alpine
COPY --from=frontend-builder /app/dist /usr/share/nginx/html
COPY --from=widget-builder /app/dist/opendc-door-designer.iife.js /usr/share/nginx/html/widget/opendc-door-designer.iife.js
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 443
