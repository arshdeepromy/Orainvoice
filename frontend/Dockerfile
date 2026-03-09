# Multi-platform support: works on both ARM64 (Apple Silicon) and AMD64 (x86_64)
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
