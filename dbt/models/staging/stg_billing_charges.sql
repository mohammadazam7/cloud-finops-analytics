-- Every billing line from both sources in one shape: snake_case FOCUS columns, typed,
-- timestamps in UTC, and a flag saying which source and whether the row is synthetic.
-- Downstream models never read the raw tables directly.
with sample as (

    select
        cast(BillingAccountId as {{ dbt.type_string() }}) as billing_account_id,
        cast(BillingAccountName as {{ dbt.type_string() }}) as billing_account_name,
        cast(SubAccountId as {{ dbt.type_string() }}) as sub_account_id,
        cast(SubAccountName as {{ dbt.type_string() }}) as sub_account_name,
        cast(ProviderName as {{ dbt.type_string() }}) as provider_name,
        cast(PublisherName as {{ dbt.type_string() }}) as publisher_name,
        cast(InvoiceIssuerName as {{ dbt.type_string() }}) as invoice_issuer_name,
        cast(ServiceCategory as {{ dbt.type_string() }}) as service_category,
        cast(ServiceName as {{ dbt.type_string() }}) as service_name,
        cast(RegionId as {{ dbt.type_string() }}) as region_id,
        cast(SkuId as {{ dbt.type_string() }}) as sku_id,
        cast(ResourceId as {{ dbt.type_string() }}) as resource_id,
        cast(ChargeCategory as {{ dbt.type_string() }}) as charge_category,
        cast(ChargeClass as {{ dbt.type_string() }}) as charge_class,
        cast(ChargeFrequency as {{ dbt.type_string() }}) as charge_frequency,
        cast(CommitmentDiscountId as {{ dbt.type_string() }}) as commitment_discount_id,
        cast(CommitmentDiscountStatus as {{ dbt.type_string() }}) as commitment_discount_status,
        cast(BillingCurrency as {{ dbt.type_string() }}) as billing_currency,
        cast(BilledCost as {{ dbt.type_float() }}) as billed_cost,
        cast(EffectiveCost as {{ dbt.type_float() }}) as effective_cost,
        cast(ListCost as {{ dbt.type_float() }}) as list_cost,
        cast(ContractedCost as {{ dbt.type_float() }}) as contracted_cost,
        cast(ConsumedQuantity as {{ dbt.type_float() }}) as consumed_quantity,
        cast(PricingQuantity as {{ dbt.type_float() }}) as pricing_quantity,
        {{ utc_timestamp('BillingPeriodStart') }} as billing_period_start,
        {{ utc_timestamp('BillingPeriodEnd') }} as billing_period_end,
        {{ utc_timestamp('ChargePeriodStart') }} as charge_period_start,
        {{ utc_timestamp('ChargePeriodEnd') }} as charge_period_end,
        false as is_synthetic,
        'focus_sample' as source_dataset
    from {{ source('raw', 'focus_sample') }}

),

synthetic as (

    select
        cast(BillingAccountId as {{ dbt.type_string() }}) as billing_account_id,
        cast(BillingAccountName as {{ dbt.type_string() }}) as billing_account_name,
        cast(SubAccountId as {{ dbt.type_string() }}) as sub_account_id,
        cast(SubAccountName as {{ dbt.type_string() }}) as sub_account_name,
        cast(ProviderName as {{ dbt.type_string() }}) as provider_name,
        cast(PublisherName as {{ dbt.type_string() }}) as publisher_name,
        cast(InvoiceIssuerName as {{ dbt.type_string() }}) as invoice_issuer_name,
        cast(ServiceCategory as {{ dbt.type_string() }}) as service_category,
        cast(ServiceName as {{ dbt.type_string() }}) as service_name,
        cast(RegionId as {{ dbt.type_string() }}) as region_id,
        cast(SkuId as {{ dbt.type_string() }}) as sku_id,
        cast(ResourceId as {{ dbt.type_string() }}) as resource_id,
        cast(ChargeCategory as {{ dbt.type_string() }}) as charge_category,
        cast(ChargeClass as {{ dbt.type_string() }}) as charge_class,
        cast(ChargeFrequency as {{ dbt.type_string() }}) as charge_frequency,
        cast(CommitmentDiscountId as {{ dbt.type_string() }}) as commitment_discount_id,
        cast(CommitmentDiscountStatus as {{ dbt.type_string() }}) as commitment_discount_status,
        cast(BillingCurrency as {{ dbt.type_string() }}) as billing_currency,
        cast(BilledCost as {{ dbt.type_float() }}) as billed_cost,
        cast(EffectiveCost as {{ dbt.type_float() }}) as effective_cost,
        cast(ListCost as {{ dbt.type_float() }}) as list_cost,
        cast(ContractedCost as {{ dbt.type_float() }}) as contracted_cost,
        cast(ConsumedQuantity as {{ dbt.type_float() }}) as consumed_quantity,
        cast(PricingQuantity as {{ dbt.type_float() }}) as pricing_quantity,
        {{ utc_timestamp('BillingPeriodStart') }} as billing_period_start,
        {{ utc_timestamp('BillingPeriodEnd') }} as billing_period_end,
        {{ utc_timestamp('ChargePeriodStart') }} as charge_period_start,
        {{ utc_timestamp('ChargePeriodEnd') }} as charge_period_end,
        true as is_synthetic,
        'synthetic_charges' as source_dataset
    from {{ source('raw', 'synthetic_charges') }}

)

select * from sample
union all
select * from synthetic
