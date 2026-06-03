import { Price } from "../value-objects/Price";
import { Duration } from "../value-objects/Duration";
import { ServiceColor } from "../value-objects/ServiceColor";
import { UserId } from "../value-objects/UserId";

export interface ServiceProps {
  id: UserId;
  name: string;
  description: string | null;
  duration: Duration;
  price: Price;
  color: ServiceColor;
  imageUrl: string | null;
  youtubeTrailerUrl: string | null;
  isActive: boolean;
}

export class Service {
  private props: ServiceProps;

  private constructor(props: ServiceProps) {
    this.props = props;
  }

  static create(props: Omit<ServiceProps, "id">): Service {
    return new Service({
      ...props,
      id: UserId.create(crypto.randomUUID()),
    });
  }

  static fromPrimitives(props: {
    id: string;
    name: string;
    description: string | null;
    duration_minutes: number;
    price: number;
    color: string | null;
    image_url: string | null;
    youtube_trailer_url: string | null;
    is_active: boolean;
  }): Service {
    return new Service({
      id: UserId.create(props.id),
      name: props.name,
      description: props.description,
      duration: Duration.create(props.duration_minutes),
      price: Price.create(props.price),
      color: ServiceColor.create(props.color || "#6366f1"),
      imageUrl: props.image_url,
      youtubeTrailerUrl: props.youtube_trailer_url,
      isActive: props.is_active,
    });
  }

  get id() { return this.props.id.getValue(); }
  get name() { return this.props.name; }
  get description() { return this.props.description; }
  get duration() { return this.props.duration; }
  get price() { return this.props.price; }
  get color() { return this.props.color.getValue(); }
  get imageUrl() { return this.props.imageUrl; }
  get youtubeTrailerUrl() { return this.props.youtubeTrailerUrl; }
  get isActive() { return this.props.isActive; }

  toPrimitives() {
    return {
      id: this.props.id.getValue(),
      name: this.props.name,
      description: this.props.description,
      duration_minutes: this.props.duration.getValue(),
      price: this.props.price.getValue(),
      color: this.props.color.getValue(),
      image_url: this.props.imageUrl,
      youtube_trailer_url: this.props.youtubeTrailerUrl,
      is_active: this.props.isActive,
    };
  }
}
