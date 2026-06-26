from modules.stores.model import Store
from modules.stores.schemas import (
    BusinessHourPeriod,
    StoreCustomField,
    StoreFeatureFlags,
    StoreResponse,
)


def to_store_response(store: Store) -> StoreResponse:
    return StoreResponse(
        public_id=store.public_id,
        name=store.name,
        slug=store.slug,
        business_type=store.business_type,
        logo_url=store.logo_url,
        primary_color=store.primary_color,
        cover_url=store.cover_url,
        description=store.description,
        whatsapp_number=store.whatsapp_number,
        instagram_url=store.instagram_url,
        facebook_url=store.facebook_url,
        website_url=store.website_url,
        custom_client_fields=[
            StoreCustomField.model_validate(field)
            for field in store.custom_client_fields
        ],
        cancellation_hours=store.cancellation_hours,
        buffer_minutes=store.buffer_minutes,
        business_hours={
            day: [BusinessHourPeriod.model_validate(period) for period in periods]
            for day, periods in store.business_hours.items()
        },
        send_email_confirmation=store.send_email_confirmation,
        send_email_reminders=store.send_email_reminders,
        feature_flags=StoreFeatureFlags.model_validate(store.normalized_feature_flags),
    )
