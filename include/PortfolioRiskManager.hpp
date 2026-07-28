#pragma once

#include "Types.hpp"

namespace AlphaNode {

struct SizeRequest {
    double account_balance{};
    double stop_loss_distance{};  // fractional price distance, e.g. 0.02 = 2%
    double price{};
    Decision decision{Decision::Hold};
    FilterSpec filters{};
};

struct SizeResult {
    double notional_value{};  // V_t
    double qty{};
    Status status{Status::Invalid};
};

// TDD stub — implement until risk_size_test.cpp is green.
class PortfolioRiskManager {
public:
    static constexpr double kRiskFraction = 0.01;

    SizeResult size(const SizeRequest& req) {
        (void)req;
        return {};
    }
};

}  // namespace AlphaNode
