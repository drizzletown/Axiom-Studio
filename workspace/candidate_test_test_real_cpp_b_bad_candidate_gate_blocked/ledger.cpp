#include "ledger.hpp"
bool Ledger::move(int amount) {
    if (amount <= 0 || amount > from || to + amount > 3) return false;
    from += amount;
    to += amount;
    return true;
}
