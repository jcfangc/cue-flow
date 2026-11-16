"""Valid statically typed construction of a nested generated model."""

from __future__ import annotations

import generated as api


def build_query() -> api.Query:
    range_value = api.QueryFilterRange(topK=5, active=True)
    filter_value = api.QueryFilter(sequence="ACGT", range=range_value)
    details_value = api.QueryDetails(label="valid")
    return api.Query.model_validate(
        {
            "id": "q1",
            "filter.sequence": "root-level",
            "wire/route/path": "root-slash",
            "wire~1name": "tilde",
            "wire/name": "slash",
            "filter": filter_value,
            "wire": api.QueryWire.model_validate({"route/path": "nested-slash"}),
            "details": details_value,
        }
    )
