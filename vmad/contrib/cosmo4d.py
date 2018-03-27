from vmad import Builder, autooperator
from vmad.lib import fastpm, mpi, linalg

from pmesh.pm import ParticleMesh

@autooperator
class FastPMOperator:
    ain = [('x', '*')]
    aout = [('rho', '*')]

    def main(self, x, q, stages, cosmology, powerspectrum, pm):
        wnk = fastpm.as_complex_field(x, pm)

        rhok = fastpm.induce_correlation(wnk, powerspectrum, pm)

        if len(stages) == 0:
            rho = fastpm.c2r(rhok)
            rho = linalg.add(rho, 1.0)
        else:
            dx, p, f = fastpm.nbody(rhok, q, stages, cosmology, pm)
            x = linalg.add(q, dx)
            layout = fastpm.decompose(x, pm)
            rho = fastpm.paint(x, mass=1, layout=layout, pm=pm)

        return dict(rho = rho)

@autooperator
class ResidualOperator:
    ain = [('x', '*')]
    aout = [('y', '*')]
    def main(self, x, d, ForwardOperator):
        rho = ForwardOperator(x)
        r = linalg.add(rho, d * -1)

        return dict(y = r)

@autooperator
class PriorOperator:
    ain = [('x', '*')]
    aout = [('y', '*')]
    def main(self, x):
        return dict(y = x)

@autooperator
class ChiSquareOperator:
    ain = [('x', '*')]
    aout = [('y', '*')]

    def main(self, x, comm):
        chi2 = linalg.sum(linalg.mul(x, x))
        chi2 = mpi.allreduce(chi2, comm)
        return dict(y = chi2)

from abopt.abopt2 import real_vector_space, Problem as BaseProblem, VectorSpace

class ChiSquareProblem(BaseProblem):

    def __init__(self, comm, operators):
        """
        """
        self.operators = operators
        self.comm = comm

        with Builder() as m:
            x = m.input('x')
            y = 0
            # fixme: need a way to directly include a subgraphs
            # rather than building it again.
            for operator in self.operators:
                r = operator(x=x)
                chi2 = ChiSquareOperator(r, comm)
            y = linalg.add(y, chi2)
            m.output(y=y)

        def objective(x):
            print('obj', (x**2).sum())
            return m.compute(vout='y', init=dict(x=x))

        def gradient(x):
            print('grad', (x**2).sum())
            y, [vjp] = m.compute_with_vjp(init=dict(x=x), v=dict(_y=1.0))
            return vjp

        def hessian_vector_product(x, v):
            print('hvp', (x**2).sum())
            Dv = 0
            for graph in self.operators:
                y, [Dv1] = graph.build().compute_with_gnDp(vout='y', init=dict(x=x), v=dict(x_=v))
                Dv = Dv + Dv1
            # H is 2 JtJ, see wikipedia on Gauss Newton.
            return Dv * 2

        vs = real_vector_space

        BaseProblem.__init__(self,
                        vs = vs,
                        objective=objective,
                        gradient=gradient,
                        hessian_vector_product=hessian_vector_product)

