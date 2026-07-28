// Step 3 — ExpectedReturnModel (docs/test-cases.md E1–E5)
#include <doctest/doctest.h>

#include "ExpectedReturnModel.hpp"

using namespace AlphaNode;

TEST_CASE("E1 E[R] = sum P_k f_k matches golden") {
    ExpectedReturnModel model(Friction{0.001, 0.001, 0.001});
    const std::vector<double> P{0.25, 0.75};
    const std::vector<double> f{0.02, -0.01};
    // 0.25*0.02 + 0.75*(-0.01) = 0.005 - 0.0075 = -0.0025
    const auto r = model.evaluate(P, f);
    REQUIRE(r.status == Status::Ok);
    CHECK(r.expected_return == doctest::Approx(-0.0025));
}

TEST_CASE("E2 E[R] > hurdle -> Trade") {
    Friction fr{0.001, 0.001, 0.001};  // hurdle = 0.003
    ExpectedReturnModel model(fr);
    const std::vector<double> P{1.0, 0.0};
    const std::vector<double> f{0.01, 0.0};  // E[R]=0.01 > 0.003
    const auto r = model.evaluate(P, f);
    REQUIRE(r.status == Status::Ok);
    CHECK(r.decision == Decision::Trade);
    CHECK(r.side != Side::None);
}

TEST_CASE("E3 E[R] <= hurdle -> HOLD") {
    Friction fr{0.001, 0.001, 0.001};
    ExpectedReturnModel model(fr);
    const std::vector<double> P{1.0};
    const std::vector<double> f{0.001};  // below hurdle 0.003
    const auto r = model.evaluate(P, f);
    REQUIRE(r.status == Status::Ok);
    CHECK(r.decision == Decision::Hold);
    CHECK(r.side == Side::None);
}

TEST_CASE("E4 E[R] == hurdle -> HOLD (strict >)") {
    Friction fr{0.001, 0.001, 0.001};  // 0.003
    ExpectedReturnModel model(fr);
    const std::vector<double> P{1.0};
    const std::vector<double> f{0.003};
    const auto r = model.evaluate(P, f);
    REQUIRE(r.status == Status::Ok);
    CHECK(r.decision == Decision::Hold);
}

TEST_CASE("E5 upstream Invalid -> HOLD/Invalid; no trade") {
    ExpectedReturnModel model(Friction{0.001, 0.001, 0.001});
    const auto r = model.evaluate({1.0}, {0.5}, Status::Invalid);
    CHECK(r.status == Status::Invalid);
    CHECK(r.decision == Decision::Hold);
    CHECK(r.side == Side::None);
}
