```mermaid
flowchart LR
  %% Vista general del proceso (MX / Meta Ads Library)
  A[Input: Lista de búsquedas<br/>(marcas, asociaciones)] --> B[Construir URL de búsqueda]
  B --> C[Abrir Meta Ads Library (MX)]
  C --> D{¿Hay anuncios?}
  D -- Sí --> E[Tomar tarjetas visibles]
  E --> F[Extraer campos:<br/>• Publicador • Fecha • Texto]
  F --> G[Quitar duplicados]
  G --> H{¿Cargar más?<br/>(scroll)}
  H -- Sí --> C
  H -- No --> I{¿Hay más términos?}
  D -- No --> I
  I -- Sí --> B
  I -- No --> J[Unir y exportar Excel mensual]
  J --> K[Usar para análisis/decisiones]
