from citeverify.verify import quote_in_source


def test_quote_matches_with_whitespace_and_case():
    source = "This prevents units from co-adapting too much during training."
    quote = "this prevents units from   co-adapting too much"
    assert quote_in_source(quote, source)


def test_quote_with_ellipsis_matches_fragments():
    source = "The method is appropriate for non-stationary objectives and noisy gradients."
    quote = "The method is appropriate ... noisy gradients"
    assert quote_in_source(quote, source)


def test_quote_not_in_source():
    source = "The source reports a 12% improvement."
    assert not quote_in_source("The source reports a 30% improvement.", source)
    assert not quote_in_source("", source)
