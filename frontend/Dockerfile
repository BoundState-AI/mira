FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_COGNITO_USER_POOL_ID
ARG VITE_COGNITO_CLIENT_ID
ARG VITE_API_AUTH_HOSTS
ENV VITE_COGNITO_USER_POOL_ID=${VITE_COGNITO_USER_POOL_ID}
ENV VITE_COGNITO_CLIENT_ID=${VITE_COGNITO_CLIENT_ID}
ENV VITE_API_AUTH_HOSTS=${VITE_API_AUTH_HOSTS}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
