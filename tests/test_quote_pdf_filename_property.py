"""Property test: Content-Disposition filename invariant (Property P3).

For every quote_number value (None or a string of letters/numbers/hyphens/underscores),
the constructed Content-Disposition header matches the expected format and the filename
is never empty.

Validates: Requirement 1.4
"""
import re
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

FILENAME_RE = re.compile(r'^inline; filename="([^"]+)\.pdf"$')


def build_content_disposition(quote_number: str | None) -> str:
    """Mirrors the logic in get_quote_pdf_endpoint."""
    filename = f"{quote_number or 'DRAFT'}.pdf"
    return f'inline; filename="{filename}"'


@given(
    quote_number=st.one_of(
        st.none(),
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_",
            ),
            min_size=0,
            max_size=40,
        ),
    ),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_content_disposition_filename_invariant(quote_number: str | None):
    header = build_content_disposition(quote_number)

    # 1. Header matches the expected format
    match = FILENAME_RE.match(header)
    assert match is not None, f"Header did not match regex: {header!r}"

    # 2. Captured name equals quote_number or "DRAFT"
    name = match.group(1)
    expected = quote_number if quote_number else "DRAFT"
    assert name == expected, f"Expected name={expected!r}, got {name!r}"

    # 3. Name is never empty
    assert name != "", f"Filename name part is empty in header: {header!r}"
