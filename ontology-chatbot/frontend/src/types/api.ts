export interface ApiError {
  detail: string;
  status_code?: number;
}

export interface ProfileResponse {
  name: string;
  display_name?: string;
  description?: string;
  database_type?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
