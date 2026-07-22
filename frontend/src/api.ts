export type ApiEnvelope<T> = { ok: boolean; data: T; meta?: { count?: number; total_count?: number; published_run_id?: string | null } }

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_API_TOKEN || ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  if (API_TOKEN) headers.set('Authorization', `Bearer ${API_TOKEN}`)
  if (init?.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || body.error || `API error ${response.status}`)
  return body as T
}

export type Product = {
  country_code: string; currency: string; snapshot_date: string; shop_id: number; item_id: number
  shop_name?: string; product_name?: string; brand?: string; price?: number; price_original?: number
  discount_percent?: number; monthly_sold_value?: number; rating?: number; rating_count?: number
  liked_count?: number; is_sold_out?: boolean; image_url?: string; url?: string
}
export type Signal = Product & {
  peer_median_price?: number; competitive_pressure_level?: string; competitive_pressure_score?: number
  signal_confidence?: string; peer_count?: number; price_gap_pct?: number; peer_sales_momentum_pct?: number
  snapshot_date?: string
}
export type Peer = { peer_rank: number; target_shop_id: number; target_item_id: number; relation: string; match_score: number; confidence: string; product_name?: string; brand?: string; price?: number; currency?: string }
export type Alert = { country_code?: string; snapshot_date: string; source_shop_id?: number; source_item_id?: number; alert_type: string; severity: string; metric_name: string; metric_value?: number; threshold?: number; target_shop_id?: number; target_item_id?: number; evidence?: string | Record<string, unknown> }
export type Recommendation = { country_code?: string; snapshot_date?: string; source_shop_id?: number; source_item_id?: number; currency?: string; recommendation_status: string; action: string; priority: string; confidence: string; source_price?: number; market_reference_price?: number; recommended_price?: number; recommended_discount_percent?: number; price_floor?: number; estimated_margin_pct?: number; constraint_status: string; reason_codes?: string | string[]; recommendation_text: string; evidence?: string | Record<string, unknown> }

const q = (country: string, shop?: number) => `country_code=${encodeURIComponent(country)}${shop ? `&shop_id=${shop}` : ''}`
export const api = {
  products: (country: string, shop?: number, query = '') => request<ApiEnvelope<Product[]>>(`/api/v1/products?${q(country, shop)}&limit=30${query ? `&query=${encodeURIComponent(query)}` : ''}`),
  alertsOverview: (country: string, shop?: number, severity = '') => request<ApiEnvelope<Alert[]>>(`/api/v1/alerts?${q(country, shop)}&limit=50${severity ? `&severity=${encodeURIComponent(severity)}` : ''}`),
  recommendationsOverview: (country: string, shop?: number) => request<ApiEnvelope<Recommendation[]>>(`/api/v1/recommendations?${q(country, shop)}&limit=50`),
  product: (country: string, shop: number, item: number) => request<ApiEnvelope<Product>>(`/api/v1/products/${item}?${q(country, shop)}`),
  peers: (country: string, shop: number, item: number) => request<ApiEnvelope<Peer[]>>(`/api/v1/products/${item}/peers?${q(country, shop)}&limit=5`),
  signals: (country: string, shop: number, item: number) => request<ApiEnvelope<Signal>>(`/api/v1/products/${item}/signals?${q(country, shop)}`),
  alerts: (country: string, shop: number, item: number) => request<ApiEnvelope<Alert[]>>(`/api/v1/products/${item}/alerts?${q(country, shop)}&limit=10`),
  recommendation: (country: string, shop: number, item: number) => request<ApiEnvelope<Recommendation>>(`/api/v1/products/${item}/recommendation?${q(country, shop)}`),
  chat: (message: string, context: Partial<Product>) => request<Record<string, unknown>>('/api/v1/chat', { method: 'POST', body: JSON.stringify({ message, country_code: context.country_code, shop_id: context.shop_id, item_id: context.item_id }) }),
}
