export interface ServiceResponseDTO {
  public_id: string;
  name: string;
  description: string | null;
  duration_minutes: number;
  price: number;
  color: string | null;
  image_url: string | null;
  youtube_trailer_url: string | null;
  is_active: boolean;
}

export interface CreateServiceRequestDTO {
  name: string;
  description?: string;
  duration_minutes: number;
  price: number;
  color?: string;
  image_url?: string;
  youtube_trailer_url?: string;
}
