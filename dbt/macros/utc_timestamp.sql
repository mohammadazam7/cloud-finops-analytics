{# Billing timestamps are instants in UTC. Convert to a naive UTC timestamp explicitly so
   the result never depends on the session time zone of whoever runs the build. #}
{% macro utc_timestamp(column) -%}
    {{ return(adapter.dispatch('utc_timestamp')(column)) }}
{%- endmacro %}

{% macro default__utc_timestamp(column) -%}
    timezone('UTC', {{ column }})
{%- endmacro %}

{% macro bigquery__utc_timestamp(column) -%}
    {{ column }}
{%- endmacro %}
