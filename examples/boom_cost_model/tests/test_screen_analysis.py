from examples.boom_cost_model.analyze_screen import rank_agreement


def test_proxy_ties_are_not_scored_as_rank_predictions():
    report = rank_agreement([(0.0, 1.0), (0.0, 2.0), (1.0, 3.0)])
    assert report["tied_proxy_pairs"] == 1
    assert report["comparable_pairs"] == 2
    assert report["pair_rank_accuracy"] == 1.0
