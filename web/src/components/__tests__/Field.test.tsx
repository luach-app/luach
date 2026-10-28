import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { EmailChips } from '../EmailChips'
import { Input, Select, Textarea } from '../Field'

/** A hint under a field was read by nobody who could not see it: it was not linked to the field. */
describe('a field’s hint', () => {
  it('describes its input, text area and select', () => {
    render(
      <>
        <Input label="Starts" hint="In your own time zone." />
        <Textarea label="Notes" hint="Only the family sees these." />
        <Select label="Calendar" hint="Where it goes.">
          <option>Home</option>
        </Select>
        <Input label="Plain" />
      </>,
    )
    expect(screen.getByLabelText('Starts')).toHaveAccessibleDescription('In your own time zone.')
    expect(screen.getByLabelText('Notes')).toHaveAccessibleDescription('Only the family sees these.')
    expect(screen.getByLabelText('Calendar')).toHaveAccessibleDescription('Where it goes.')
    expect(screen.getByLabelText('Plain')).not.toHaveAttribute('aria-describedby')
  })

  it('keeps what the caller already said describes it', () => {
    render(
      <>
        <p id="extra">Also this.</p>
        <Input label="Name" hint="As the family says it." aria-describedby="extra" />
      </>,
    )
    expect(screen.getByLabelText('Name')).toHaveAccessibleDescription('Also this. As the family says it.')
  })

  it('on a list of addresses, describes it, and then says what is wrong', async () => {
    render(<EmailChips label="Invite" value={[]} onChange={() => {}} hint="Everyone here gets an invitation." />)
    const box = screen.getByLabelText('Invite')
    expect(box).toHaveAccessibleDescription('Everyone here gets an invitation.')
    await userEvent.type(box, 'not-an-address{Enter}')
    expect(box).toHaveAccessibleDescription('That is not an email address.')
    expect(box).toHaveAttribute('aria-invalid', 'true')
  })
})
