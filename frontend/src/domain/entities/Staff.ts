import { Email } from '../value-objects/Email';
import { UserId } from '../value-objects/UserId';

export interface StaffProps {
  id: UserId;
  firstName: string;
  lastName: string;
  email: Email;
  displayName: string | null;
  isActive: boolean;
  serviceIds: string[];
}

export class Staff {
  private props: StaffProps;

  private constructor(props: StaffProps) {
    this.props = props;
  }

  static create(props: Omit<StaffProps, 'id' | 'isActive'>): Staff {
    return new Staff({
      ...props,
      id: UserId.create(crypto.randomUUID()),
      isActive: true,
    });
  }

  static fromPrimitives(props: {
    public_id: string;
    first_name: string;
    last_name: string;
    email: string;
    display_name: string | null;
    is_active: boolean;
    service_ids: string[];
  }): Staff {
    return new Staff({
      id: UserId.create(props.public_id),
      firstName: props.first_name,
      lastName: props.last_name,
      email: Email.create(props.email),
      displayName: props.display_name,
      isActive: props.is_active,
      serviceIds: props.service_ids,
    });
  }

  // Getters
  get id() { return this.props.id.getValue(); }
  get firstName() { return this.props.firstName; }
  get lastName() { return this.props.lastName; }
  get email() { return this.props.email; }
  get displayName() { return this.props.displayName ?? this.fullName; }
  get isActive() { return this.props.isActive; }
  get serviceIds() { return [...this.props.serviceIds]; }

  get role(): 'ADMIN' | 'STAFF' {
    if (this.email.getValue().toLowerCase().includes('admin')) {
      return 'ADMIN';
    }
    return 'STAFF';
  }

  get fullName(): string {
    return `${this.props.firstName} ${this.props.lastName}`.trim();
  }

  // Business Logic
  assignToService(serviceId: string): void {
    if (!this.props.serviceIds.includes(serviceId)) {
      this.props.serviceIds.push(serviceId);
    }
  }

  removeFromService(serviceId: string): void {
    this.props.serviceIds = this.props.serviceIds.filter(id => id !== serviceId);
  }

  toPrimitives() {
    return {
      public_id: this.props.id.getValue(),
      first_name: this.props.firstName,
      last_name: this.props.lastName,
      email: this.props.email.getValue(),
      display_name: this.props.displayName,
      is_active: this.props.isActive,
      service_ids: [...this.props.serviceIds],
    };
  }
}
