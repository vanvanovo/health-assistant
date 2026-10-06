# frontend/Dockerfile — 构建 Vue3 产物并由 nginx 托管(反代 /api 到 gateway)
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
