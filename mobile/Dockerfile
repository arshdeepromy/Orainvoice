FROM node:20-alpine

WORKDIR /app

# Copy and install dependencies first (cached unless package.json changes)
COPY mobile/package.json mobile/package-lock.json* ./
RUN npm install --no-audit && npm install @rollup/rollup-linux-arm64-musl 2>/dev/null || true

# Copy shared types (needed for TypeScript compilation)
COPY shared/ /shared/

# Copy mobile app source
COPY mobile/ .

# Always build fresh — never use pre-existing dist
RUN rm -rf dist && npx vite build

# Default: just keep the container alive (nginx serves the files)
CMD ["node", "-e", "setInterval(()=>{},60000)"]
