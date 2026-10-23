FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS dependencies
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
FROM dependencies AS build
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend ./
RUN npm run format:check && npm run build
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -g 10001 -S quarry && adduser -S quarry -u 10001 -G quarry \
    && rm -rf /usr/local/lib/node_modules /opt/yarn-* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg
COPY --from=build --chown=quarry:quarry /app/.next/standalone ./
COPY --from=build --chown=quarry:quarry /app/.next/static ./.next/static
USER 10001:10001
EXPOSE 3000
CMD ["node", "server.js"]

FROM mcr.microsoft.com/playwright:v1.64.1-noble@sha256:7852dc5a7d72f5fe458a597d690f6c42fbc8e9e26ddfa95f8e6ef552558d9bbf AS browser-tests
WORKDIR /app
ENV CI=1 NEXT_TELEMETRY_DISABLED=1
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY --chown=pwuser:pwuser frontend/tests ./tests
COPY --chown=pwuser:pwuser frontend/playwright.config.ts ./playwright.config.ts
COPY --chown=pwuser:pwuser frontend/src/app/api ./frontend/src/app/api
COPY --chown=pwuser:pwuser security/review-probes ./security/review-probes
RUN ln -s /app/node_modules /app/frontend/node_modules && mkdir -p /app/evaluation/results && chown -R pwuser:pwuser /app/evaluation
USER pwuser
CMD ["npx", "playwright", "test"]
