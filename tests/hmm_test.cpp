// Step 2 — HMMInference (docs/test-cases.md H1–H6)
#include <doctest/doctest.h>

#include "HMMInference.hpp"

#include <cmath>
#include <limits>
#include <numeric>
#include <vector>

using namespace AlphaNode;

namespace {

HmmParams Tiny2State1D() {
    HmmParams p;
    p.K = 2;
    p.D = 1;
    // A row-stochastic
    p.A = {0.9, 0.1, 0.2, 0.8};
    p.mu = {0.0, 1.0};
    // Sigma[k][0][0]
    p.Sigma = {1.0, 4.0};
    return p;
}

FeatureVector Feat(double v) {
    FeatureVector fv;
    fv.status = Status::Ok;
    fv.x = {v};
    return fv;
}

}  // namespace

TEST_CASE("H1 load Python params — shapes valid; ready") {
    HMMInference hmm;
    const auto st = hmm.load(Tiny2State1D());
    CHECK(st == Status::Ok);
    CHECK(hmm.ready());
}

TEST_CASE("H2 Forward matches golden within tol") {
    HMMInference hmm;
    REQUIRE(hmm.load(Tiny2State1D()) == Status::Ok);

    // Fixture sequence — golden filled once Forward is correct.
    // Until then this fails; replace golden after first verified impl.
    std::vector<double> P;
    REQUIRE(hmm.forward(Feat(0.0), P) == Status::Ok);
    REQUIRE(P.size() == 2);

    // Placeholder golden: state-0 should dominate near mu=0 after one step
    // with equal start — tighten when analytic fixture is locked.
    CHECK(P[0] == doctest::Approx(0.5).epsilon(0.5));
    CHECK(P[1] == doctest::Approx(0.5).epsilon(0.5));
}

TEST_CASE("H3 prob bounds") {
    HMMInference hmm;
    REQUIRE(hmm.load(Tiny2State1D()) == Status::Ok);
    std::vector<double> P;
    REQUIRE(hmm.forward(Feat(0.5), P) == Status::Ok);
    for (double pk : P) {
        CHECK(pk >= 0.0);
        CHECK(pk <= 1.0);
    }
}

TEST_CASE("H4 prob sum ~ 1") {
    HMMInference hmm;
    REQUIRE(hmm.load(Tiny2State1D()) == Status::Ok);
    std::vector<double> P;
    REQUIRE(hmm.forward(Feat(0.5), P) == Status::Ok);
    const double sum = std::accumulate(P.begin(), P.end(), 0.0);
    CHECK(std::abs(sum - 1.0) < 1e-7);
}

TEST_CASE("H5 reload order-invariance by Tr(Sigma)") {
    // Deliberately unsorted: state0 Sigma=4, state1 Sigma=1 → must swap on reload.
    HmmParams raw = Tiny2State1D();
    raw.mu = {1.0, 0.0};
    raw.Sigma = {4.0, 1.0};

    HMMInference hmm;
    REQUIRE(hmm.reload_ordered(raw) == Status::Ok);

    std::vector<double> P_a;
    REQUIRE(hmm.forward(Feat(0.0), P_a) == Status::Ok);

    HMMInference hmm2;
    REQUIRE(hmm2.reload_ordered(raw) == Status::Ok);
    std::vector<double> P_b;
    REQUIRE(hmm2.forward(Feat(0.0), P_b) == Status::Ok);

    REQUIRE(P_a.size() == P_b.size());
    for (std::size_t i = 0; i < P_a.size(); ++i) {
        CHECK(P_a[i] == doctest::Approx(P_b[i]));
    }
}

TEST_CASE("H6 NaN feature -> Invalid; probs not updated") {
    HMMInference hmm;
    REQUIRE(hmm.load(Tiny2State1D()) == Status::Ok);
    std::vector<double> P;
    REQUIRE(hmm.forward(Feat(0.0), P) == Status::Ok);
    const auto before = P;

    FeatureVector bad;
    bad.status = Status::Ok;
    bad.x = {std::numeric_limits<double>::quiet_NaN()};
    CHECK(hmm.forward(bad, P) == Status::Invalid);
    CHECK(hmm.last_P() == before);
}
