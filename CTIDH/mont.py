import numpy
from .primefield import PrimeField
from .utils import read_prime_info, attrdict, CMOV, CSWAP, memoize, binrep, read_SDAC_info


# MontgomeryCurve class determines the family of supersingular elliptic curves over GF(p)


@memoize
def MontgomeryCurve(prime_name="p1024_CTIDH", SDAC=False, validation="origin"):
    if validation not in ["origin", "doliskani", "pairing1", "pairing2"]:
        raise ValueError

    prime_info = read_prime_info(prime_name)

    L = prime_info["L"]
    n = prime_info["n"]
    k = prime_info["k"]
    f = prime_info["f"]
    p = prime_info["p"]

    batch_start = prime_info["batch_start"]
    batch_stop = prime_info["batch_stop"]
    batch_maxdaclen = prime_info["batch_maxdaclen"]
    # batch_bound = prime_info["batch_bound"]

    field = PrimeField(p)

    type_field = type(field(2))

    # Shortest Differential Addition Chains (SDACs) for each l_i, used in fast scalar multiplication.
    SDACS = read_SDAC_info(prime_name)
    assert len(SDACS) > 0, f'No precomputed sdac information for {prime_name}'
    SDACS_LENGTH = list(map(len, SDACS))
    SDACS_REVERSED = list(map(lambda x:x[::-1], SDACS))


    def cmul(l: int):
        return numpy.array([4.0 * (SDACS_LENGTH[L.index(l)] + 2), 2.0 * (SDACS_LENGTH[L.index(l)] + 2), 6.0 * (SDACS_LENGTH[L.index(l)] + 2) - 2.0])
    c_xmul = list(map(cmul, L))  # list of the costs of each [l]P

    def measure(x, SQR=1.00, ADD=0.00):
        """
        Field additions, multiplications, and squarings
        SQR = 1.00
        # In F_p, we have SQR_{F_p} = SQR x MUL_{F_p}
        ADD = 0.00
        # In F_p, we have ADD_{F_p} = ADD x MUL_{F_p}
        """
        return x[0] + SQR * x[1] + ADD * x[2]


    def elligator(A: tuple):
        """Elligator from CTIDH original implementation (NOT Elligator 2)

        Args:
            A (tuple): tuple of ZModPrime class objects (Ax, Az), represent
              A = Ax / Az , or (Ax: Az) in P^1

        Returns:
            T+, T- (tuple):  projective x-coordinates of random points on EA(Fp) and EA(Fp^2) respectively.
            T- is the proj x-coord of point (x, iy) correspond to EA^t(Fp)'s point (-x, y)) .
                Each of them is a tuple like (Tx, Tz), and Tx, Tz are ZModPrime class object
        """
        Ax, Az = A

        # Check if Ax and Az are ZModPrime objects
        # Can't write isinstance(Ax, ZModPrime) here because my ZModPrime is inside the func PrimeField().
        # This can cause some invisible bugs with sage's GF element
        # if not hasattr(Ax, "value") or not hasattr(Az, "value"):

        # Now change to
        if not isinstance(Ax, type_field) or not isinstance(Az, type_field):
            raise TypeError("Input must be ZModPrime type tuple!")

        while True:
            one = field(1)

            # TODO: Change to a nice random generator
            u = field.get_random()  # line 1 of my pseudocode
            if u == 0:
                continue
            u2 = u**2
            D = u2 - 1
            if D == 0:
                continue  # line 7 of my pseudocode

            M = u2 * Ax
            T = M * Ax
            ctrl = Ax == 0
            P = Ax
            P = CMOV(P, one, ctrl)  # line 12 of my pseudocode
            M = CMOV(M, one, ctrl)
            T = CMOV(T, one, ctrl)
            D = D * Az
            D2 = D**2
            T = T + D2
            T = T * D
            T = T * P  # line 19 of my pseudocode

            Tplus_x = P
            Tminus_x = -M
            ctrl = not T.is_square()
            Tplus_x, Tminus_x = CSWAP(Tplus_x, Tminus_x, ctrl)

            Tplus_z = D
            Tminus_z = D

            return (Tplus_x, Tplus_z), (Tminus_x, Tminus_z)

    def affine_to_projective(affine) -> tuple:
        """
        affine_to_projective()
        input : the affine Montgomery coefficient A=A'/C with C=1
        output: projective Montgomery constants A24 := A' + 2C and C24 := 4C
                where E : y^2 = x^3 + (A'/C)*x^2 + x
        """
        return (affine + field(2), field(4))

    # def coeff(A24: tuple):
    #     """
    #     ----------------------------------------------------------------------
    #     coeff()
    #     input : projective Montgomery constants A24 := A + 2C and C24 := 4C
    #             where E : y^2 = x^3 + (A/C)*x^2 + x
    #     output: the affine Montgomery coefficient A/C
    #     ----------------------------------------------------------------------
    #     """
    #     A24, C24 = A24
    #     output = A24 + A24  # (2 * A24)
    #     output -= C24  # (2 * A24) - C24
    #     C24_inv = C24 ** (-1)  # 1 / (C24)
    #     output += output  # 4*A = 2[(2 * A24) - C24]
    #     output *= C24_inv  # A/C = 2[(2 * A24) - C24] / C24

    #     return output

    def xA24(A: tuple) -> tuple:
        Ax, Az = A
        two_Az = Az + Az
        return (Ax - two_Az, two_Az + two_Az)

    def isinfinity(P):
        """isinfinity(P) determines if x(P) := (XP : ZP) = (1 : 0)"""
        return P[1] == 0

    def isequal(P, Q):
        """isequal(P, Q) determines if x(P) = x(Q)"""
        return (P[0] * Q[1]) == (P[1] * Q[0])

    def xdbl(P: tuple, A24: tuple) -> tuple:
        """
        ----------------------------------------------------------------------
        xdbl()
        input : a projective Montgomery x-coordinate point x(P) := XP/ZP, and
                the  projective Montgomery constants A24:= A + 2C and C24:=4C
                where E : y^2 = x^3 + (A/C)*x^2 + x
        output: the projective Montgomery x-coordinate point x([2]P)
        ----------------------------------------------------------------------
        """
        XP, ZP = P
        #TODO: Remove this unnecessary assert
        assert XP != 0 and ZP != 0

        V1 = XP + ZP  # line 1 of my pseudo code
        V1 **= 2
        V2 = XP - ZP
        V2 **= 2
        Z2P = A24[1] * V2
        X2P = Z2P * V1  # line 6 of my pseudo code

        V1 -= V2
        Z2P += A24[0] * V1
        Z2P *= V1

        return (X2P, Z2P)

    def xadd(P: tuple, Q: tuple, PQ: tuple) -> tuple:
        """
        ----------------------------------------------------------------------
        xadd()
        input : the projective Montgomery x-coordinate points x(P) := XP/ZP,
                x(Q) := XQ/ZQ, and x(P-Q) := XPQ/ZPQ
        output: the projective Montgomery x-coordinate point x(P+Q)
        ----------------------------------------------------------------------
        """
        XP, ZP = P
        XQ, ZQ = Q
        XPQ, ZPQ = PQ
        # assert XPQ != 0

        V0 = XP + ZP
        V1 = XQ - ZQ
        V1 = V1 * V0
        V0 = XP - ZP
        V2 = XQ + ZQ
        V2 = V2 * V0
        V3 = V1 + V2

        V3 **= 2
        V4 = V1 - V2
        V4 **= 2
        X_plus = ZPQ * V3
        Z_plus = XPQ * V4
        # if ZPQ == 0:
        #     assert X_plus == 0 and Z_plus == 0 
            # X_plus = 1; Z_plus = 0
        return (X_plus, Z_plus)
    

    def crisscross(alpha, beta, gamma, delta):
        """ crisscross() computes a*c + b*d, and a*c - b*d """
        t_1 = (alpha * delta)
        t_2 = (beta * gamma)
        #return (t_1 + t_2), (t_1 - t_2)
        # shave off a FF allocation: ##
        t_3 = t_1.copy() # object.__new__(t_1.__class__); t_3.x = t_1.x #      ## copy(t_1)
        t_1 += t_2                    ##
        t_3 -= t_2                   ##
        return t_1, t_3 # (t_1 + t_2), (t_1 - t_2)


    def xmul_Ladder(P: tuple, A24: tuple, j: int) -> tuple:
        """
        ----------------------------------------------------------------------
        xmul_Ladder():  Constant-time Montgomery Ladder
        input : a projective Montgomery x-coordinate point x(P) := XP/ZP, the
                projective Montgomery constants A24:= A + 2C and C24:=4C where
                E : y^2 = x^3 + (A/C)*x^2 + x, and an positive integer j
        output: the projective Montgomery x-coordinate point x([L[j]]P)
        ----------------------------------------------------------------------
        """
        XP, ZP = P
        #TODO: Remove this unnecessary assert
        assert XP != 0 and ZP != 0
        kbits = binrep(L[j])
        kbitlen = len(kbits)

        x0, x1 = xdbl(P, A24), P
        for i in reversed(range(kbitlen-1)):
            x0, x1 = CSWAP(x0, x1, kbits[i+1] ^ kbits[i])
            x0, x1 = xdbl(x0, A24), xadd(x0, x1, P)
        x0, x1 = CSWAP(x0, x1, kbits[0])
        
        return x0


    def xmul_SDAC(P: tuple, A24: tuple, j: int) -> tuple:
        """
        ----------------------------------------------------------------------
        Scalar mult for PUBLIC primes that use Shortest Differential Addition Chain (SDAC)
        input : a projective Montgomery x-coordinate point x(P) := XP/ZP, the
                projective Montgomery constants A24:= A + 2C and C24:=4C where
                E : y^2 = x^3 + (A/C)*x^2 + x, and an positive integer j
        output: the projective Montgomery x-coordinate point x([L[j]]P)
        ----------------------------------------------------------------------
        """
        raise NotImplementedError


    def xmul_SDAC_safe(P: tuple, A24: tuple, j: int) -> tuple:
        """
        ----------------------------------------------------------------------
        Timing attack safe scalar mult for PRIVATE primes that use Shortest Differential Addition Chain (SDAC).
        This algorithm consider each batch's max dac length to resist timing attack.
        input : a projective Montgomery x-coordinate point x(P) := XP/ZP, the
                projective Montgomery constants A24:= A + 2C and C24:=4C where
                E : y^2 = x^3 + (A/C)*x^2 + x, and an positive integer j
        output: the projective Montgomery x-coordinate point x([L[j]]P)
        ----------------------------------------------------------------------
        """
        # NOTE: Use batch_maxdaclen to achieve security.
        raise NotImplementedError

    xmul_public = xmul_SDAC if SDAC else xmul_Ladder
    xmul_private = xmul_SDAC_safe if SDAC else xmul_Ladder

    # TODO: Add more useful things such as PRAC, eucild2d, cofactor_multiples, crisscross...
    # Read papers and see sibc...

    # TODO: Decide whether these verification algorithms should use A24 or affine A
    def issupersingular_origin(A: tuple):
        raise NotImplementedError

    def issupersingular_doliskani(A: tuple):
        raise NotImplementedError

    def issupersingular_pairing1(A: tuple):
        raise NotImplementedError

    def issupersingular_pairing2(A: tuple):
        raise NotImplementedError

    validation_options = {
        "origin": issupersingular_origin,
        "doliskani": issupersingular_doliskani,
        "pairing1": issupersingular_pairing1,
        "pairing2": issupersingular_pairing2,
    }

    issupersingular = validation_options[validation]

    return attrdict(**locals())
