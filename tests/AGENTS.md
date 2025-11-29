# Unit Testing

## Principles
* **Tests Should Be Fast**
* Tests Should Be Independent: Each test should be able to run individually and as part of the test suite, irrespective of the sequence in which it’s executed.
* **Each Test Should Test One Thing**: A test unit should concentrate on one small functionality and verify its correctness.
* **Tests Should Be Readable**: Use Sound Naming Conventions
* **Tests Should Be Deterministic**: avoids relying on external factors like file or network dependencies, or random data
* **Tests Should Not Include Implementation Details**: Tests should verify behaviour, not implementation details. They should focus on what the code does, not how it does it.
* **Use Single Assert Per Test Method**: Each test should aim to verify a single aspect of the code, making it easier to identify the cause of any failures. Eg:
```python
def test_user_first_name():  
    user = UserProfile('John', 'Doe')  
    assert user.first_name == 'John'  
  
def test_user_last_name():  
    user = UserProfile('John', 'Doe')  
    assert user.last_name == 'Doe'  
  
def test_user_full_name():  
    user = UserProfile('John', 'Doe')  
    assert user.full_name() == 'John Doe'
```
* **Use Fake Data/Databases in Testing**
* **Use Dependency Injection**
* **Use Setup and Teardown To Isolate Test Dependencies**. Eg:
```python
@pytest.fixture  
def resource_setup():  
    # Setup code: Create resource  
    resource = "some resource"  
    print("Resource created")  
      
    # This yield statement is where the test execution will take place  
    yield resource  
  
    # Teardown code: Release resource  
    print("Resource released")  
  
def test_example(resource_setup):  
    assert resource_setup == "some resource"
```
* **Group Related Tests**. All tests related to xxx.py should reside in test_xxx.py. All tests related to `User` class should reside in `TestUser` class. All tests related to `xxx` funtion, should reside in `TestXxxFunction` class.
* **Mock Where Necessary**: Replace parts of your system under test with mock objects, isolating tests from external dependencies, or for white-box tests(enforcing branches those triggered by hard-to-prove execptions).
* **Use Test Framework Features To Your Advantage**: Key among these in Pytest are conftest.py, fixtures, and parameterization.
    * **[conftest.py](conftest.py)** serves as a central place for fixture definitions, making them accessible across multiple test files, thereby promoting reuse and reducing code duplication.
    * **Pytest Fixtures** offer a powerful way to set up and tear down resources needed for tests, ensuring isolation and reliability.
    * **Pytest Parameterization** allows for the easy creation of multiple test cases from a single test function, enabling efficient testing of various input scenarios.
* **Regularly Review and Refactor Tests**: examining tests to ensure they remain relevant, efficient, and readable. Removing redundancy, updating tests to reflect code changes, or improving test organization and naming.

## Rules
* Each source file "xxx.py" must have its corresponding "test_xxx.py".
* Use mocks and fixtures as needed. DRY: maintain common useful mocks and fixtures in [conftest.py](conftest.py).
* Unit tests should not hit network (including, but not limited to 3rd parties APIs) nor filesystem, to avoid flackiness and keep them ultra-fast. Levarage on mocks to achieve it.
* Add good info and debug logs to testing code; use logs for debugging failing tests.
