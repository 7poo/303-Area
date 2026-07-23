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
  product_type?: string; weight_g?: number; volume_ml?: number; quantity?: number; bundle_count?: number
  is_bundle?: boolean; total_weight_g?: number; total_volume_ml?: number; package_ambiguous?: boolean
  variation_count?: number; price_variant_ambiguous?: boolean; variant_signature?: string
  family_signature?: string; company_id?: string; company_name?: string
  seller_entity_id?: string; seller_entity_name?: string
}
export type Signal = Product & {
  peer_median_price?: number; competitive_pressure_level?: string; competitive_pressure_score?: number
  source_list_price?: number; source_historical_median_price?: number; source_price_observation_count?: number
  price_baseline_value?: number; price_baseline_type?: string; price_baseline_actionable?: boolean
  signal_confidence?: string; peer_count?: number; benchmark_peer_count?: number; price_gap_pct?: number; peer_sales_momentum_pct?: number
  price_down_peer_count?: number; promotion_peer_count?: number
  snapshot_date?: string; price_comparison_basis?: string; source_normalized_price?: number; peer_median_normalized_price?: number
}
export type Peer = { peer_rank: number; target_shop_id: number; target_item_id: number; relation: string; match_score: number; confidence: string; product_name?: string; brand?: string; price?: number; currency?: string; product_type?: string; weight_g?: number; volume_ml?: number; quantity?: number; bundle_count?: number; is_bundle?: boolean; total_weight_g?: number; total_volume_ml?: number; package_ambiguous?: boolean; variation_count?: number; price_variant_ambiguous?: boolean; variant_signature?: string; family_signature?: string; company_id?: string; company_name?: string; seller_entity_id?: string; seller_entity_name?: string; model_version?: string }
export type Alert = { country_code?: string; snapshot_date: string; source_shop_id?: number; source_item_id?: number; alert_type: string; severity: string; metric_name: string; metric_value?: number; threshold?: number; target_shop_id?: number; target_item_id?: number; target_company_id?: string; target_company_name?: string; target_seller_entity_id?: string; target_seller_entity_name?: string; evidence?: string | Record<string, unknown> }
export type Recommendation = { country_code?: string; snapshot_date?: string; source_shop_id?: number; source_item_id?: number; currency?: string; recommendation_status: string; action: string; priority: string; confidence: string; source_price?: number; market_reference_price?: number; recommended_price?: number; recommended_discount_percent?: number; price_floor?: number; cost_value?: number; margin_min_pct?: number; estimated_margin_pct?: number; constraint_status: string; reason_codes?: string | string[]; recommendation_text: string; evidence?: string | Record<string, unknown> }
export type Company = { country_code: string; company_id: string; company_name: string; sku_count: number; shop_ids: number[]; distributor_names?: string[] }

const q = (country: string, shop?: number) => `country_code=${encodeURIComponent(country)}${shop ? `&shop_id=${shop}` : ''}`
export const api = {
  products: (country: string, shop?: number, query = '', company = '') => request<ApiEnvelope<Product[]>>(`/api/v1/products?${q(country, shop)}&limit=30${query ? `&query=${encodeURIComponent(query)}` : ''}${company ? `&company_id=${encodeURIComponent(company)}` : ''}`),
  companies: (country: string) => request<ApiEnvelope<Company[]>>(`/api/v1/companies?country_code=${encodeURIComponent(country)}`),
  alertsOverview: (country: string, shop?: number, severity = '', company = '') => request<ApiEnvelope<Alert[]>>(`/api/v1/alerts?${q(country, shop)}&limit=50${severity ? `&severity=${encodeURIComponent(severity)}` : ''}${company ? `&company_id=${encodeURIComponent(company)}` : ''}`),
  recommendationsOverview: (country: string, shop?: number, status = '', limit = 100, company = '') => request<ApiEnvelope<Recommendation[]>>(`/api/v1/recommendations?${q(country, shop)}&limit=${limit}${status ? `&recommendation_status=${encodeURIComponent(status)}` : ''}${company ? `&company_id=${encodeURIComponent(company)}` : ''}`),
  product: (country: string, shop: number, item: number) => request<ApiEnvelope<Product>>(`/api/v1/products/${item}?${q(country, shop)}`),
  peers: (country: string, shop: number, item: number) => request<ApiEnvelope<Peer[]>>(`/api/v1/products/${item}/peers?${q(country, shop)}&limit=5`),
  signals: (country: string, shop: number, item: number) => request<ApiEnvelope<Signal>>(`/api/v1/products/${item}/signals?${q(country, shop)}`),
  alerts: (country: string, shop: number, item: number) => request<ApiEnvelope<Alert[]>>(`/api/v1/products/${item}/alerts?${q(country, shop)}&limit=10`),
  recommendation: (country: string, shop: number, item: number) => request<ApiEnvelope<Recommendation>>(`/api/v1/products/${item}/recommendation?${q(country, shop)}`),
  chat: (message: string, context: Partial<Product>) => request<Record<string, unknown>>('/api/v1/chat', { method: 'POST', body: JSON.stringify({ message, country_code: context.country_code, shop_id: context.shop_id, item_id: context.item_id }) }),
}
