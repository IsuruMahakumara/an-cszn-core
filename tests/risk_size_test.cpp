// Step 4 — PortfolioRiskManager (docs/test-cases.md R1–R5)
#include <doctest/doctest.h>

#include "PortfolioRiskManager.hpp"

#include <cmath>

using namespace AlphaNode;

namespace {

FilterSpec BtcFilters() {
    FilterSpec f;
    f.stepSize = 0.00001;
    f.minQty = 0.00001;
    f.minNotional = 5.0;
    f.tickSize = 0.01;
    return f;
}

}  // namespace

TEST_CASE("R1 V_t * stop <= 1% balance") {
    PortfolioRiskManager rm;
    SizeRequest req;
    req.account_balance = 10'000.0;
    req.stop_loss_distance = 0.02;
    req.price = 50'000.0;
    req.decision = Decision::Trade;
    req.filters = BtcFilters();

    const auto out = rm.size(req);
    REQUIRE(out.status == Status::Ok);
    CHECK(out.notional_value * req.stop_loss_distance <=
          doctest::Approx(0.01 * req.account_balance).epsilon(1e-9));
}

TEST_CASE("R2 wider stop -> smaller V_t") {
    PortfolioRiskManager rm;
    SizeRequest base;
    base.account_balance = 10'000.0;
    base.price = 50'000.0;
    base.decision = Decision::Trade;
    base.filters = BtcFilters();

    SizeRequest narrow = base;
    narrow.stop_loss_distance = 0.01;
    SizeRequest wide = base;
    wide.stop_loss_distance = 0.04;

    const auto a = rm.size(narrow);
    const auto b = rm.size(wide);
    REQUIRE(a.status == Status::Ok);
    REQUIRE(b.status == Status::Ok);
    CHECK(b.notional_value < a.notional_value);
}

TEST_CASE("R3 floor to LOT_SIZE step; qty >= minQty when possible") {
    PortfolioRiskManager rm;
    SizeRequest req;
    req.account_balance = 10'000.0;
    req.stop_loss_distance = 0.02;
    req.price = 50'000.0;
    req.decision = Decision::Trade;
    req.filters = BtcFilters();

    const auto out = rm.size(req);
    REQUIRE(out.status == Status::Ok);
    const double step = req.filters.stepSize;
    const double n = std::round(out.qty / step);
    CHECK(out.qty == doctest::Approx(n * step).epsilon(1e-12));
    CHECK(out.qty >= req.filters.minQty);
}

TEST_CASE("R4 after floor notional < minNotional -> reject") {
    PortfolioRiskManager rm;
    SizeRequest req;
    req.account_balance = 1.0;  // tiny — forces small V_t
    req.stop_loss_distance = 0.5;
    req.price = 50'000.0;
    req.decision = Decision::Trade;
    req.filters = BtcFilters();
    req.filters.minNotional = 5.0;

    const auto out = rm.size(req);
    CHECK(out.status == Status::Invalid);
    CHECK(out.qty == doctest::Approx(0.0));
}

TEST_CASE("R5 HOLD -> zero qty / Invalid") {
    PortfolioRiskManager rm;
    SizeRequest req;
    req.account_balance = 10'000.0;
    req.stop_loss_distance = 0.02;
    req.price = 50'000.0;
    req.decision = Decision::Hold;
    req.filters = BtcFilters();

    const auto out = rm.size(req);
    CHECK(out.qty == doctest::Approx(0.0));
    CHECK(out.status == Status::Invalid);
}
