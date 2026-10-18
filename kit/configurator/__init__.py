r"""Model configurator: a small window that chooses models for the Master Chief and the executors.

The configurator writes only .pi/kit-models.json. kit/run_pi.py reads that
file and prepares the isolated Pi runtime. Run from the project root:

    kit\python.cmd -m kit.configurator.app
"""
