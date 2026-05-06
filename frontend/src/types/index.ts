export interface User {
  id: number;
  email: string;
  name: string;
  picture_url: string | null;
  is_admin: boolean;
}

export interface ValidationBlock {
  code: string;
  passed: boolean;
  severity: string;
  message: string;
  detail?: Record<string, unknown>;
  non_overridable?: boolean;
}

export interface PushPipeline {
  attach: string;   // "ok" | "skipped — ..." | "failed — ..."
  cleanup: string;  // "ok" | "skipped" | "failed — ..."
  file: string | null;
}

export interface PushResult {
  draft_id: number;
  external_bill_id: string;
  platform: string;
  pipeline: PushPipeline;
}

export interface InvoiceDraft {
  id: number;
  invoice_id: number;
  vendor_name: string | null;
  resolved_vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  total_amount: number | null;
  tax_amount: number | null;
  currency: string;
  line_items: LineItem[];
  source: string;
  push_to: string | null;
  push_to_rule_id: number | null;
  status: string;
  reviewed_by: number | null;
  reviewed_at: string | null;
  push_error: string | null;
  pushed_at: string | null;
  external_bill_id: string | null;
  invoice_type: string | null;
  account_id: number | null;
  account_name: string | null;
  tax_breakup: { cgst_amount: number; sgst_amount: number; igst_amount: number } | null;
  validation_warnings: Array<{ message: string }>;
  validation_errors: ValidationBlock[];
  itc_status: string | null;
  tds_applicable: boolean | null;
  place_of_supply: string | null;
  pdf_attached_at: string | null;
  // pipeline result from last push (null until first push attempt)
  last_pipeline: PushPipeline | null;
  created_at: string;
  updated_at: string;
}

export interface LineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number;
  hsn_or_sac: string | null;
}

export interface Rule {
  id: number;
  name: string;
  description: string | null;
  priority: number;
  is_active: boolean;
  conditions: ConditionTree;
  action_type: string;
  action_value: string;
  created_at: string;
  updated_at: string;
}

export type ConditionTree = LeafCondition | GroupCondition;

export interface LeafCondition {
  field: string;
  op: string;
  value: string | number;
}

export interface GroupCondition {
  operator: 'AND' | 'OR';
  conditions: ConditionTree[];
}

export interface VendorMapping {
  id: number;
  alias_name: string;
  canonical_name: string;
  platform: string | null;
  platform_vendor_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Integration {
  id: number;
  platform: string;
  display_name: string;
  is_enabled: boolean;
  health_status: string;
  health_checked_at: string | null;
  created_at: string;
}

export interface DashboardSummary {
  total: number;
  pending_review: number;
  pending_vendor: number;
  approved: number;
  pushed: number;
  push_failed: number;
  rejected: number;
  by_source: Record<string, number>;
  by_platform: Record<string, number>;
}

export interface ApiResponse<T> {
  status: string;
  data: T;
  message?: string;
  total?: number;
}
