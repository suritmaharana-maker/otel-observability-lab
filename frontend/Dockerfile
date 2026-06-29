# Build stage
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# Serve stage
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# SPA-friendly + a tiny runtime-config injection point.
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
