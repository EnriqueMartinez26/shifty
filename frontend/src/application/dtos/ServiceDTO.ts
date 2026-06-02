export interface ServiceResponseDTO {
  public_id: string;
  name: string;
  description: string | null;
  duration_minutes: number;
  price: number;
  color: string | null;
  youtube_trailer_url: string | null;
  is_active: boolean;
}

export interface CreateServiceRequestDTO {
  name: string;
  description?: string;
  duration_minutes: number;
  price: number;
  color?: string;
  youtube_trailer_url?: string;
}
