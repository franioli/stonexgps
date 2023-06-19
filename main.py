import sys

def run_tests():
    import pytest

    try:
        import package_name
    except ImportError as e:
        raise ImportError(e)

    retcode = pytest.main()
    sys.exit(retcode)

if __name__ == "__main__":
    run_tests()