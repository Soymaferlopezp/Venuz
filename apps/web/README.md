# Venuz Web

Frontend Next.js App Router de Venuz. Presenta identidad, aviso Paper permanente y estado público del API; no contiene secretos ni reglas financieras.

```bat
npm ci
npm run dev
```

Calidad:

```bat
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Usa únicamente variables `NEXT_PUBLIC_*` descritas en `.env.example`. Consulta el [README principal](../../README.md) para el setup completo.
