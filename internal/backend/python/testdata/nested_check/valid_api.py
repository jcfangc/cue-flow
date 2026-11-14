"""Valid statically typed construction of a nested generated model."""

from __future__ import annotations

import generated as api


def build_query() -> api.Query:
    range_value = api.QueryFilterRange(topK=5, active=True)
    filter_value = api.QueryFilter(sequence="ACGT", range=range_value)
    return api.Query(id="q1", filter=filter_value)
