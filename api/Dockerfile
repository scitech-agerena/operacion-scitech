FROM node:20-alpine
WORKDIR /app
COPY package.json ./
COPY src ./src
# config/ se monta como volumen de solo lectura (ver infra/docker-compose.yml)
USER node
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "src/server.js"]
