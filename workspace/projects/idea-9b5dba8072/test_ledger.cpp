#include "ledger.hpp"
#include <iostream>
int main() {
    Ledger l;
    if (!l.move(1) || l.from!=2 || l.to!=1) return 1;
    if (!l.move(2) || l.from!=0 || l.to!=3) return 2;
    if (l.move(1) || l.move(0) || l.from!=0 || l.to!=3) return 3;
    std::cout << "PASS ledger\n";
}
